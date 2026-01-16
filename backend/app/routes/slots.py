from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Slot
from ..schemas import SlotOut

router = APIRouter()


@router.get("/slots", response_model=list[SlotOut])
def list_slots(department: str | None = None, db: Session = Depends(get_session)) -> list[SlotOut]:
    stmt = select(Slot)
    if department:
        stmt = stmt.where(Slot.department == department)
    stmt = stmt.order_by(Slot.start_time)
    return db.scalars(stmt).all()