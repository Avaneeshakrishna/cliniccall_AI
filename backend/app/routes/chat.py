import re
import uuid
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Appointment, Patient, Slot, UrgentCase
from ..schemas import ChatRequest, ChatResponse
from ..services.email import send_confirmation_email
from ..services.llm import route_message
from ..services.npi import search_providers
from ..services.scheduler import book_slot
from ..services.triage import triage_message

router = APIRouter()
_conversations: dict[str, dict] = {}


def _get_conversation(conversation_id: str | None) -> tuple[str, dict]:
    if conversation_id and conversation_id in _conversations:
        return conversation_id, _conversations[conversation_id]
    new_id = conversation_id or uuid.uuid4().hex
    _conversations[new_id] = {
        "intent": None,
        "department": None,
        "reason": None,
        "pending_slot_id": None,
        "pending_appointment_id": None,
        "awaiting_confirmation": False,
        "awaiting_reason": False,
        "awaiting_patient": False,
        "patient_phone": None,
        "patient_email": None,
        "patient_name": None,
        "last_appointment_ids": [],
        "location_zip": None,
        "provider_choices": [],
        "awaiting_provider": False,
        "awaiting_location": False,
        "selected_provider": None,
        "awaiting_department": False,
        "provider_needs_department": False,
        "suggested_slot_ids": [],
    }
    return new_id, _conversations[new_id]


def _extract_email(message: str) -> str | None:
    match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", message)
    return match.group(0) if match else None


def _extract_phone(message: str) -> str | None:
    digits = re.sub(r"\D", "", message)
    if len(digits) >= 10:
        return digits
    return None


def _extract_zip(message: str) -> str | None:
    match = re.search(r"\b\d{5}\b", message)
    return match.group(0) if match else None


def _is_affirmative(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in ("yes", "yep", "yeah", "confirm", "sure"))


def _is_negative(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in ("no", "nope", "cancel", "stop"))


def _format_slot_time(start_time: datetime) -> str:
    return start_time.strftime("%A %I:%M %p").lstrip("0")


def _ensure_provider_slots(
    db: Session, department: str, provider_name: str
) -> bool:
    existing = db.scalars(
        select(Slot.id).where(Slot.department == department, Slot.provider == provider_name)
    ).first()
    if existing:
        return False
    today = datetime.now().date()
    slots = []
    for day_offset in range(7):
        day = today + timedelta(days=day_offset)
        start_dt = datetime.combine(day, time(9, 0))
        end_dt = datetime.combine(day, time(16, 0))
        current = start_dt
        while current <= end_dt:
            slots.append(
                Slot(
                    department=department,
                    provider=provider_name,
                    start_time=current,
                    is_booked=False,
                )
            )
            current += timedelta(minutes=30)
    db.add_all(slots)
    db.flush()
    return True


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest, db: Session = Depends(get_session)
) -> ChatResponse:
    conversation_id, state = _get_conversation(payload.conversation_id)
    if payload.patient_phone:
        state["patient_phone"] = payload.patient_phone
    if payload.patient_email:
        state["patient_email"] = payload.patient_email
    if payload.patient_name:
        state["patient_name"] = payload.patient_name

    extracted_phone = _extract_phone(payload.message)
    extracted_email = _extract_email(payload.message)
    extracted_zip = _extract_zip(payload.message)
    if extracted_phone:
        state["patient_phone"] = extracted_phone
    if extracted_email:
        state["patient_email"] = extracted_email
    if extracted_zip:
        state["location_zip"] = extracted_zip

    if state.get("awaiting_reason"):
        state["reason"] = payload.message.strip()
        state["awaiting_reason"] = False

    if state.get("awaiting_confirmation"):
        if _is_affirmative(payload.message):
            slot = None
            if state.get("pending_slot_id"):
                slot = db.get(Slot, state["pending_slot_id"])
            if not slot or slot.is_booked:
                state["awaiting_confirmation"] = False
                state["pending_slot_id"] = None
                reply = "That slot is no longer available. Would you like another time?"
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )

            phone = state.get("patient_phone")
            email = state.get("patient_email")
            name = state.get("patient_name") or "Patient"
            if not phone:
                state["awaiting_patient"] = True
                reply = "Before I book, what phone number should we use for the appointment?"
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )
            patient = db.scalars(select(Patient).where(Patient.phone == phone)).first()
            if not patient:
                if not email:
                    state["awaiting_patient"] = True
                    reply = "I couldn't find your record. What's your email so I can create it?"
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent=state.get("intent") or "BOOK",
                        department=state.get("department"),
                        reason=state.get("reason"),
                    )
                patient = Patient(name=name, phone=phone, email=email)
                db.add(patient)
                db.flush()
                db.refresh(patient)

            if state.get("pending_appointment_id"):
                appointment = db.get(Appointment, state["pending_appointment_id"])
                if appointment:
                    old_slot = db.get(Slot, appointment.slot_id)
                    if old_slot:
                        old_slot.is_booked = False
                    slot.is_booked = True
                    appointment.slot_id = slot.id
            else:
                appointment = book_slot(
                    db,
                    patient_id=patient.id,
                    slot_id=slot.id,
                    reason=state.get("reason") or payload.message,
                )

            db.commit()

            state["awaiting_confirmation"] = False
            state["pending_slot_id"] = None
            state["pending_appointment_id"] = None
            state["suggested_slot_ids"] = []
            if patient.email:
                subject = "Your appointment is confirmed"
                provider_name = slot.provider or "Provider"
                location_line = "Location: To be confirmed by the clinic."
                body = (
                    f"Hello {patient.name},\n\n"
                    f"Your {slot.department} appointment is booked for "
                    f"{_format_slot_time(slot.start_time)}.\n"
                    f"Provider: {provider_name}\n"
                    f"{location_line}\n\n"
                    "If you need to reschedule or cancel, reply in the assistant."
                )
                send_confirmation_email(patient.email, subject, body)

            reply = (
                f"You're all set. I booked {slot.department} at "
                f"{_format_slot_time(slot.start_time)}. We'll send a confirmation."
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "BOOK",
                department=slot.department,
                reason=state.get("reason"),
            )
        if _is_negative(payload.message):
            state["awaiting_confirmation"] = False
            state["pending_slot_id"] = None
            state["suggested_slot_ids"] = []
            reply = "No problem. Would you like a different time?"
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "BOOK",
                department=state.get("department"),
                reason=state.get("reason"),
            )
        if state.get("pending_slot_id"):
            slot = db.get(Slot, state["pending_slot_id"])
            if slot:
                reply = (
                    f"Please confirm booking {slot.department} at "
                    f"{_format_slot_time(slot.start_time)} (yes/no)."
                )
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=slot.department,
                    reason=state.get("reason"),
                )

    if _is_affirmative(payload.message) and state.get("intent") == "BOOK":
        department = state.get("department")
        if department:
            stmt = (
                select(Slot)
                .where(Slot.department == department, Slot.is_booked.is_(False))
                .order_by(Slot.start_time)
                .limit(5)
            )
            suggested_slots = db.scalars(stmt).all()
            state["suggested_slot_ids"] = [slot.id for slot in suggested_slots]
            reply = (
                f"Here are the next available {department} times. "
                "Select a slot and I will confirm before booking."
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent="BOOK",
                department=department,
                reason=state.get("reason"),
                suggested_slots=suggested_slots,
            )
        reply = (
            "Which department do you want to book, "
            "Dermatology, Cardiology, General Medicine, Pediatrics, or Orthopedics?"
        )
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            intent="BOOK",
            department=None,
            reason=state.get("reason"),
        )

    if state.get("awaiting_patient"):
        phone = state.get("patient_phone")
        email = state.get("patient_email")
        if not phone:
            reply = "What phone number is the appointment under?"
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "OTHER",
                department=state.get("department"),
                reason=state.get("reason"),
            )

        if state.get("intent") in {"RESCHEDULE", "CANCEL"}:
            state["awaiting_patient"] = False
            patient = db.scalars(select(Patient).where(Patient.phone == phone)).first()
            if not patient:
                reply = "I couldn't find an appointment with that phone number."
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "OTHER",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )
            appointments = db.scalars(
                select(Appointment).where(
                    Appointment.patient_id == patient.id,
                    Appointment.status == "booked",
                )
            ).all()
            if not appointments:
                reply = (
                    "I don't see any upcoming appointments to reschedule."
                    if state.get("intent") == "RESCHEDULE"
                    else "I don't see any upcoming appointments to cancel."
                )
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "OTHER",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )
            state["last_appointment_ids"] = [appt.id for appt in appointments]
            lines = []
            for idx, appt in enumerate(appointments, start=1):
                slot = db.get(Slot, appt.slot_id)
                if slot:
                    lines.append(
                        f"{idx}) {slot.department} at {_format_slot_time(slot.start_time)}"
                    )
            if state.get("intent") == "RESCHEDULE":
                reply = "Which appointment should we reschedule? " + " ".join(lines)
            else:
                reply = "Which appointment should I cancel? " + " ".join(lines)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "OTHER",
                department=state.get("department"),
                reason=state.get("reason"),
            )

        if state.get("pending_slot_id"):
            if not email:
                reply = "What's your email so I can complete the booking?"
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )
            state["awaiting_patient"] = False
            state["awaiting_confirmation"] = True
            slot = db.get(Slot, state["pending_slot_id"])
            if slot:
                reply = (
                    f"Thanks. Please confirm booking {slot.department} at "
                    f"{_format_slot_time(slot.start_time)} (yes/no)."
                )
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=slot.department,
                    reason=state.get("reason"),
                )

    if state.get("last_appointment_ids"):
        selection = payload.message.strip()
        if selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(state["last_appointment_ids"]):
                appointment = db.get(
                    Appointment, state["last_appointment_ids"][index]
                )
                state["last_appointment_ids"] = []
                if not appointment:
                    reply = "I couldn't find that appointment. Please try again."
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent=state.get("intent") or "OTHER",
                        department=state.get("department"),
                        reason=state.get("reason"),
                    )
                slot = db.get(Slot, appointment.slot_id)
                if state.get("intent") == "CANCEL":
                    with db.begin():
                        appointment.status = "canceled"
                        if slot:
                            slot.is_booked = False
                    reply = "Your appointment has been canceled."
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent="CANCEL",
                        department=slot.department if slot else None,
                        reason=state.get("reason"),
                    )
                if state.get("intent") == "RESCHEDULE":
                    state["pending_appointment_id"] = appointment.id
                    department = slot.department if slot else state.get("department")
                    if department:
                        stmt = (
                            select(Slot)
                            .where(
                                Slot.department == department,
                                Slot.is_booked.is_(False),
                            )
                            .order_by(Slot.start_time)
                            .limit(5)
                        )
                        suggested_slots = db.scalars(stmt).all()
                        state["suggested_slot_ids"] = [slot.id for slot in suggested_slots]
                        reply = (
                            f"Here are the next available {department} times. "
                            "Select one and I will confirm the reschedule."
                        )
                        return ChatResponse(
                            conversation_id=conversation_id,
                            reply=reply,
                            intent="RESCHEDULE",
                            department=department,
                            reason=state.get("reason"),
                            suggested_slots=suggested_slots,
                        )
                    reply = "Which department should I reschedule to?"
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent="RESCHEDULE",
                        department=None,
                        reason=state.get("reason"),
                    )
        reply = "Please reply with the number of the appointment from the list."
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            intent=state.get("intent") or "OTHER",
            department=state.get("department"),
            reason=state.get("reason"),
        )

    if state.get("awaiting_provider"):
        selection = payload.message.strip()
        if selection.isdigit():
            index = int(selection) - 1
            choices = state.get("provider_choices") or []
            if 0 <= index < len(choices):
                provider = choices[index]
                state["awaiting_provider"] = False
                state["provider_choices"] = []
                provider_name = provider["name"]
                state["selected_provider"] = provider_name
                department = state.get("department")
                default_note = ""
                if not department:
                    department = "General Medicine"
                    state["department"] = department
                    default_note = (
                        "I didn't catch a department, so I'm showing General Medicine slots. "
                        "Say another department if you'd like."
                    )
                if state.get("provider_needs_department"):
                    state["provider_needs_department"] = False
                    if not department:
                        state["awaiting_department"] = True
                        reply = "Which department should I use for this provider?"
                        return ChatResponse(
                            conversation_id=conversation_id,
                            reply=reply,
                            intent=state.get("intent") or "BOOK",
                            department=department,
                            reason=state.get("reason"),
                        )
                if not department:
                    reply = "Which department is this appointment for?"
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent=state.get("intent") or "BOOK",
                        department=None,
                        reason=state.get("reason"),
                    )
                created = _ensure_provider_slots(db, department, provider_name)
                if created:
                    db.commit()
                stmt = (
                    select(Slot)
                    .where(
                        Slot.department == department,
                        Slot.provider == provider_name,
                        Slot.is_booked.is_(False),
                    )
                    .order_by(Slot.start_time)
                    .limit(5)
                )
                suggested_slots = db.scalars(stmt).all()
                state["suggested_slot_ids"] = [slot.id for slot in suggested_slots]
                reply = (
                    f"{default_note} Here are the next available times with {provider_name}. "
                    "Select a slot and I will confirm before booking."
                ).strip()
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent="BOOK",
                    department=department,
                    reason=state.get("reason"),
                    suggested_providers=[],
                    suggested_slots=suggested_slots,
                )
        reply = "Please reply with the number of the provider from the list."
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            intent=state.get("intent") or "BOOK",
            department=state.get("department"),
            reason=state.get("reason"),
        )

    if state.get("awaiting_department"):
        result = await route_message(payload.message)
        department = result.get("department")
        if not department:
            reply = (
                "Which department should I use? Options: Dermatology, Cardiology, "
                "General Medicine, Pediatrics, Orthopedics."
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "BOOK",
                department=state.get("department"),
                reason=state.get("reason"),
            )
        state["department"] = department
        state["awaiting_department"] = False
        provider_name = state.get("selected_provider")
        if provider_name:
            created = _ensure_provider_slots(db, department, provider_name)
            if created:
                db.commit()
            stmt = (
                select(Slot)
                .where(
                    Slot.department == department,
                    Slot.provider == provider_name,
                    Slot.is_booked.is_(False),
                )
                .order_by(Slot.start_time)
                .limit(5)
            )
            suggested_slots = db.scalars(stmt).all()
            state["suggested_slot_ids"] = [slot.id for slot in suggested_slots]
            reply = (
                f"Here are the next available times with {provider_name}. "
                "Select a slot and I will confirm before booking."
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent="BOOK",
                department=department,
                reason=state.get("reason"),
                suggested_slots=suggested_slots,
            )

    if state.get("suggested_slot_ids"):
        selection = payload.message.strip()
        if selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(state["suggested_slot_ids"]):
                slot_id = state["suggested_slot_ids"][index]
                slot = db.get(Slot, slot_id)
                state["suggested_slot_ids"] = []
                if slot and not slot.is_booked:
                    state["pending_slot_id"] = slot.id
                    state["awaiting_confirmation"] = True
                    if not state.get("reason"):
                        state["awaiting_reason"] = True
                        reply = "What is the reason for the visit?"
                    else:
                        reply = (
                            f"You selected {slot.department} at "
                            f"{_format_slot_time(slot.start_time)}. Please confirm (yes/no)."
                        )
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent=state.get("intent") or "BOOK",
                        department=slot.department,
                        reason=state.get("reason"),
                    )
                reply = "That slot is no longer available. Please choose another time."
                return ChatResponse(
                    conversation_id=conversation_id,
                    reply=reply,
                    intent=state.get("intent") or "BOOK",
                    department=state.get("department"),
                    reason=state.get("reason"),
                )

    if state.get("location_zip") and (state.get("awaiting_location") or extracted_zip):
        department = state.get("department") or ""
        providers, fallback_note = await search_providers(
            department, state["location_zip"], limit=5
        )
        if not providers:
            reply = (
                f"I couldn't find nearby {state.get('department') or 'providers'}. "
                "Could you share a different ZIP code?"
            )
        else:
            state["provider_choices"] = providers
            state["awaiting_provider"] = True
            state["awaiting_location"] = False
            state["provider_needs_department"] = fallback_note is not None
            lines = []
            for idx, provider in enumerate(providers, start=1):
                city = provider.get("city") or ""
                state_code = provider.get("state") or ""
                lines.append(f"{idx}) {provider['name']} ({city} {state_code})")
            if fallback_note == "broader":
                prefix = (
                    "I couldn't find that specialty nearby, so here are general providers in the area. "
                )
            elif fallback_note == "nearby":
                prefix = (
                    "I couldn't find an exact match in that ZIP, but here are providers nearby. "
                )
            else:
                prefix = "Here are nearby providers. "
            reply = prefix + "Reply with a number: " + " ".join(lines)
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent=state.get("intent") or "BOOK",
                department=state.get("department"),
                reason=state.get("reason"),
                suggested_providers=providers,
            )
        return ChatResponse(
            conversation_id=conversation_id,
            reply=reply,
            intent=state.get("intent") or "BOOK",
            department=state.get("department"),
            reason=state.get("reason"),
        )

    result = await route_message(payload.message)
    intent = result["intent"]
    department = result.get("department")
    reason = result.get("reason")
    suggested_slots: list[Slot] = []
    urgent_case_id = None
    if payload.selected_slot_id and intent == "OTHER":
        intent = "BOOK"
    state["intent"] = intent
    if department:
        state["department"] = department
    if reason:
        state["reason"] = reason

    if intent == "URGENT":
        triage_result = await triage_message(payload.message)
        urgent_case = UrgentCase(
            patient_id=payload.patient_id,
            severity=triage_result["severity"],
            summary=triage_result["summary"],
            transcript=payload.message,
            status="received",
        )
        db.add(urgent_case)
        db.commit()
        db.refresh(urgent_case)
        urgent_case_id = urgent_case.id
        reply = (
            "Thanks for letting us know. Based on what you shared, this sounds urgent. "
            "If you are in immediate danger or have severe symptoms, please call emergency "
            "services right now. Otherwise, a clinician will review this and reach out shortly."
        )
    elif intent == "BOOK":
        if payload.selected_slot_id:
            slot = db.get(Slot, payload.selected_slot_id)
            if slot and not slot.is_booked:
                state["pending_slot_id"] = slot.id
                state["awaiting_confirmation"] = True
                if not state.get("reason"):
                    state["awaiting_reason"] = True
                    reply = "What is the reason for the visit?"
                else:
                    reply = (
                        f"You selected {slot.department} at "
                        f"{_format_slot_time(slot.start_time)}. Please confirm (yes/no)."
                    )
            else:
                reply = "That slot is no longer available. Please choose another time."
        elif not reason or len(reason.split()) < 2:
            state["awaiting_reason"] = True
            reply = "What is the reason for the visit?"
        elif department and state.get("selected_provider"):
            provider_name = state["selected_provider"]
            created = _ensure_provider_slots(db, department, provider_name)
            if created:
                db.commit()
            stmt = (
                select(Slot)
                .where(
                    Slot.department == department,
                    Slot.provider == provider_name,
                    Slot.is_booked.is_(False),
                )
                .order_by(Slot.start_time)
                .limit(5)
            )
            suggested_slots = db.scalars(stmt).all()
            state["suggested_slot_ids"] = [slot.id for slot in suggested_slots]
            reply = (
                f"Here are the next available times with {provider_name}. "
                "Select a slot and I will confirm before booking."
            )
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent="BOOK",
                department=department,
                reason=state.get("reason"),
                suggested_slots=suggested_slots,
            )
        elif department:
            location_zip = state.get("location_zip")
            if not location_zip:
                state["awaiting_location"] = True
                reply = "What is your 5-digit ZIP code so I can find nearby providers?"
            else:
                providers, fallback_note = await search_providers(
                    department, location_zip, limit=5
                )
                if not providers:
                    reply = (
                        f"I couldn't find nearby {department} providers. "
                        "Could you share a different ZIP code?"
                    )
                else:
                    state["provider_choices"] = providers
                    state["awaiting_provider"] = True
                    state["provider_needs_department"] = fallback_note is not None
                    lines = []
                    for idx, provider in enumerate(providers, start=1):
                        city = provider.get("city") or ""
                        state_code = provider.get("state") or ""
                        lines.append(
                            f"{idx}) {provider['name']} ({city} {state_code})"
                        )
                    if fallback_note == "broader":
                        prefix = (
                            "I couldn't find that specialty nearby, so here are general providers in the area. "
                        )
                    elif fallback_note == "nearby":
                        prefix = (
                            "I couldn't find an exact match in that ZIP, but here are providers nearby. "
                        )
                    else:
                        prefix = "Here are nearby providers. "
                    reply = prefix + "Reply with a number: " + " ".join(lines)
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent="BOOK",
                        department=department,
                        reason=state.get("reason"),
                        suggested_providers=providers,
                    )
        else:
            location_zip = state.get("location_zip")
            if location_zip:
                providers, fallback_note = await search_providers("", location_zip, limit=5)
                if providers:
                    state["provider_choices"] = providers
                    state["awaiting_provider"] = True
                    state["provider_needs_department"] = fallback_note is not None
                    lines = []
                    for idx, provider in enumerate(providers, start=1):
                        city = provider.get("city") or ""
                        state_code = provider.get("state") or ""
                        lines.append(
                            f"{idx}) {provider['name']} ({city} {state_code})"
                        )
                    if fallback_note == "broader":
                        prefix = (
                            "I couldn't find providers in that ZIP, so here are general providers nearby. "
                        )
                    elif fallback_note == "nearby":
                        prefix = (
                            "I couldn't find providers in that ZIP, but here are nearby. "
                        )
                    else:
                        prefix = "Here are nearby providers. "
                    reply = prefix + "Reply with a number, then tell me the department."
                    return ChatResponse(
                        conversation_id=conversation_id,
                        reply=reply,
                        intent="BOOK",
                        department=None,
                        reason=state.get("reason"),
                        suggested_providers=providers,
                    )
            reply = (
                "I can help book an appointment. Which department do you need, "
                "Dermatology, Cardiology, General Medicine, Pediatrics, or Orthopedics?"
            )
    elif intent == "RESCHEDULE":
        state["awaiting_patient"] = False
        if payload.selected_slot_id and state.get("pending_appointment_id"):
            slot = db.get(Slot, payload.selected_slot_id)
            if slot and not slot.is_booked:
                state["pending_slot_id"] = slot.id
                state["awaiting_confirmation"] = True
                reply = (
                    f"You selected {slot.department} at "
                    f"{_format_slot_time(slot.start_time)}. Please confirm (yes/no)."
                )
            else:
                reply = "That slot is no longer available. Please choose another time."
            return ChatResponse(
                conversation_id=conversation_id,
                reply=reply,
                intent="RESCHEDULE",
                department=slot.department if slot else None,
                reason=state.get("reason"),
            )
        phone = state.get("patient_phone")
        if not phone:
            state["awaiting_patient"] = True
            reply = "Sure. What phone number is the appointment under?"
        else:
            patient = db.scalars(select(Patient).where(Patient.phone == phone)).first()
            if not patient:
                reply = "I couldn't find an appointment with that phone number."
            else:
                appointments = db.scalars(
                    select(Appointment).where(
                        Appointment.patient_id == patient.id,
                        Appointment.status == "booked",
                    )
                ).all()
                if not appointments:
                    reply = "I don't see any upcoming appointments to reschedule."
                else:
                    state["last_appointment_ids"] = [appt.id for appt in appointments]
                    lines = []
                    for idx, appt in enumerate(appointments, start=1):
                        slot = db.get(Slot, appt.slot_id)
                        if slot:
                            lines.append(
                                f"{idx}) {slot.department} at {_format_slot_time(slot.start_time)}"
                            )
                    reply = "Which appointment should we reschedule? " + " ".join(lines)
    elif intent == "CANCEL":
        state["awaiting_patient"] = False
        phone = state.get("patient_phone")
        if not phone:
            state["awaiting_patient"] = True
            reply = "Sure. What phone number is the appointment under?"
        else:
            patient = db.scalars(select(Patient).where(Patient.phone == phone)).first()
            if not patient:
                reply = "I couldn't find an appointment with that phone number."
            else:
                appointments = db.scalars(
                    select(Appointment).where(
                        Appointment.patient_id == patient.id,
                        Appointment.status == "booked",
                    )
                ).all()
                if not appointments:
                    reply = "I don't see any upcoming appointments to cancel."
                else:
                    state["last_appointment_ids"] = [appt.id for appt in appointments]
                    lines = []
                    for idx, appt in enumerate(appointments, start=1):
                        slot = db.get(Slot, appt.slot_id)
                        if slot:
                            lines.append(
                                f"{idx}) {slot.department} at {_format_slot_time(slot.start_time)}"
                            )
                    reply = "Which appointment should I cancel? " + " ".join(lines)
    elif intent == "FAQ":
        reply = "I can answer general questions or help you book an appointment."
    else:
        reply = (
            "I can help with booking, rescheduling, cancellations, or urgent concerns. "
            "What would you like to do?"
        )

    return ChatResponse(
        conversation_id=conversation_id,
        reply=reply,
        intent=intent,
        department=department,
        reason=reason,
        suggested_slots=suggested_slots,
        urgent_case_id=urgent_case_id,
    )
