import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .db import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)

    appointments = relationship("Appointment", back_populates="patient")
    urgent_cases = relationship("UrgentCase", back_populates="patient")


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    appointment = relationship("Appointment", back_populates="slot", uselist=False)


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="booked")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="appointments")
    slot = relationship("Slot", back_populates="appointment")


class UrgentCase(Base):
    __tablename__ = "urgent_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    transcript: Mapped[str] = mapped_column(String(5000), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", back_populates="urgent_cases")