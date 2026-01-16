from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict

Intent = Literal["BOOK","RESCHEDULE","CANCEL","FAQ","URGENT","OTHER"]

class SlotOut(BaseModel):
    id: str
    department: str
    provider: str
    start_time: datetime
    is_booked: bool

    model_config = ConfigDict(from_attributes=True)


class AppointmentCreate(BaseModel):
    patient_id: str
    slot_id: str
    reason: str


class AppointmentOut(BaseModel):
    id: str
    patient_id: str
    slot_id: str
    reason: str
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PatientCreate(BaseModel):
    name: str
    phone: str
    email: str


class PatientOut(BaseModel):
    id: str
    name: str
    phone: str
    email: str

    model_config = ConfigDict(from_attributes=True)


class PatientLookupRequest(BaseModel):
    phone: str
    name: Optional[str] = None
    email: Optional[str] = None


class AppointmentVoiceCreate(BaseModel):
    phone: str
    slot_id: str
    reason: str
    name: Optional[str] = None
    email: Optional[str] = None


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    patient_id: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    patient_name: Optional[str] = None
    selected_slot_id: Optional[str] = None
    selected_provider_npi: Optional[str] = None
    message: str


class ProviderSuggestion(BaseModel):
    npi: str
    name: str
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    intent: Intent
    department: Optional[str] = None
    reason: Optional[str] = None
    suggested_providers: list[ProviderSuggestion] = []
    suggested_slots: list[SlotOut] = []
    urgent_case_id: Optional[str] = None


class TriageRequest(BaseModel):
    message: str


class TriageResponse(BaseModel):
    severity: str
    summary: str
    escalate: bool


class UrgentCaseOut(BaseModel):
    id: str
    patient_id: str | None
    severity: str
    summary: str
    transcript: str
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
