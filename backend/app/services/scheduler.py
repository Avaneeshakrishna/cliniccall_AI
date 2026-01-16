from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import Appointment, Slot


def schedule_follow_up(patient_id: str, summary: str, when: datetime) -> dict:
    return {
        "status": "stub",
        "patient_id": patient_id,
        "summary": summary,
        "scheduled_for": when.isoformat(),
    }


def book_slot(db: Session, patient_id: str, slot_id: str, reason: str) -> Appointment:
    result = db.execute(
        update(Slot)
        .where(Slot.id == slot_id, Slot.is_booked.is_(False))
        .values(is_booked=True)
        .returning(Slot)
    )
    slot = result.scalar_one_or_none()
    if slot is None:
        raise ValueError("Slot already booked")

    appointment = Appointment(
        patient_id=patient_id,
        slot_id=slot_id,
        reason=reason,
        status="booked",
    )
    db.add(appointment)
    db.flush()
    db.refresh(appointment)
    return appointment
