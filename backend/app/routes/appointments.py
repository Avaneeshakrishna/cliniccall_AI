from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..auth import require_auth, require_voice_token
from ..models import Patient, Slot
from ..schemas import AppointmentCreate, AppointmentOut, AppointmentVoiceCreate
from ..services.email import send_confirmation_email
from ..services.scheduler import book_slot

router = APIRouter()


@router.post("/appointments/book", response_model=AppointmentOut)
def book_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_session),
    _auth: dict = Depends(require_auth),
) -> AppointmentOut:
    patient = db.get(Patient, payload.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        with db.begin():
            appointment = book_slot(
                db,
                patient_id=payload.patient_id,
                slot_id=payload.slot_id,
                reason=payload.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if patient.email:
        slot = db.get(Slot, payload.slot_id)
        if slot:
            provider_name = slot.provider or "Provider"
            location_line = "Location: To be confirmed by the clinic."
            body = (
                f"Hello {patient.name},\n\n"
                f"Your {slot.department} appointment is booked for "
                f"{slot.start_time.strftime('%A %I:%M %p').lstrip('0')}.\n"
                f"Provider: {provider_name}\n"
                f"{location_line}\n\n"
                "If you need to reschedule or cancel, reply in the assistant."
            )
        else:
            body = (
                "Your appointment has been booked. Please contact the clinic if you need changes."
            )
        send_confirmation_email(
            patient.email,
            "Your appointment is confirmed",
            body,
        )
    return appointment


@router.post("/appointments/voice-book", response_model=AppointmentOut)
def voice_book_appointment(
    payload: AppointmentVoiceCreate,
    db: Session = Depends(get_session),
    _auth: None = Depends(require_voice_token),
) -> AppointmentOut:
    try:
        with db.begin():
            stmt = select(Patient).where(Patient.phone == payload.phone)
            patient = db.scalars(stmt).first()
            if not patient:
                name = payload.name or "Voice Caller"
                if payload.email:
                    email = payload.email
                else:
                    safe_phone = "".join(ch for ch in payload.phone if ch.isdigit())
                    email = f"caller_{safe_phone or 'unknown'}@voice.local"
                patient = Patient(
                    name=name,
                    phone=payload.phone,
                    email=email,
                )
                db.add(patient)
                db.flush()
                db.refresh(patient)

            appointment = book_slot(
                db,
                patient_id=patient.id,
                slot_id=payload.slot_id,
                reason=payload.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if patient.email:
        slot = db.get(Slot, payload.slot_id)
        if slot:
            provider_name = slot.provider or "Provider"
            location_line = "Location: To be confirmed by the clinic."
            body = (
                f"Hello {patient.name},\n\n"
                f"Your {slot.department} appointment is booked for "
                f"{slot.start_time.strftime('%A %I:%M %p').lstrip('0')}.\n"
                f"Provider: {provider_name}\n"
                f"{location_line}\n\n"
                "If you need to reschedule or cancel, reply in the assistant."
            )
        else:
            body = (
                "Your appointment has been booked. Please contact the clinic if you need changes."
            )
        send_confirmation_email(
            patient.email,
            "Your appointment is confirmed",
            body,
        )
    return appointment
