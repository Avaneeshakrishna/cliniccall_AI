from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_session
from ..models import UrgentCase
from ..schemas import TriageRequest, TriageResponse, UrgentCaseOut
from ..services.triage import triage_message

router = APIRouter()


@router.post("/triage", response_model=TriageResponse)
async def triage(
    payload: TriageRequest, db: Session = Depends(get_session)
) -> TriageResponse:
    result = await triage_message(payload.message)
    if result["escalate"] or result["severity"] != "ROUTINE":
        urgent_case = UrgentCase(
            patient_id=None,
            severity=result["severity"],
            summary=result["summary"],
            transcript=payload.message,
            status="received",
        )
        db.add(urgent_case)
        db.commit()

    return TriageResponse(
        severity=result["severity"],
        summary=result["summary"],
        escalate=result["escalate"],
    )


@router.get("/urgent_cases", response_model=list[UrgentCaseOut])
def list_urgent_cases(
    db: Session = Depends(get_session), _auth: dict = Depends(require_auth)
) -> list[UrgentCaseOut]:
    stmt = select(UrgentCase).order_by(UrgentCase.created_at.desc())
    return db.scalars(stmt).all()
