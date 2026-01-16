from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Patient
from ..schemas import PatientLookupRequest, PatientOut

router = APIRouter()


@router.post("/patients/ensure", response_model=PatientOut)
def ensure_patient(
    payload: PatientLookupRequest, db: Session = Depends(get_session)
) -> PatientOut:
    stmt = select(Patient).where(Patient.phone == payload.phone)
    patient = db.scalars(stmt).first()
    if patient:
        return patient

    if not payload.name or not payload.email:
        raise HTTPException(
            status_code=400,
            detail="Name and email are required to create a new patient",
        )

    patient = Patient(
        name=payload.name,
        phone=payload.phone,
        email=payload.email,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient
