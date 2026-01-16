import uuid
from datetime import datetime, time, timedelta

from faker import Faker
from sqlalchemy import func, select

from .db import SessionLocal
from .models import Patient, Slot


DEPARTMENTS = [
    ("Dermatology", "Dr. Patel"),
    ("Cardiology", "Dr. Nguyen"),
    ("General Medicine", "Dr. Rivera"),
    ("Pediatrics", "Dr. Kim"),
    ("Orthopedics", "Dr. Shah"),
]


def seed_data() -> None:
    db = SessionLocal()
    try:
        patient_count = db.scalar(select(func.count()).select_from(Patient))
        if not patient_count:
            fake = Faker()
            patients = []
            for _ in range(25):
                patients.append(
                    Patient(
                        id=str(uuid.uuid4()),
                        name=fake.name(),
                        phone=fake.phone_number(),
                        email=fake.email(),
                    )
                )
            db.add_all(patients)

        slot_count = db.scalar(select(func.count()).select_from(Slot))
        existing_departments = set()
        if slot_count:
            existing_departments = set(
                db.scalars(select(Slot.department).distinct()).all()
            )

        missing_departments = [
            (department, provider)
            for department, provider in DEPARTMENTS
            if department not in existing_departments
        ]

        if not slot_count or missing_departments:
            today = datetime.now().date()
            slots = []
            target_departments = (
                missing_departments if slot_count else DEPARTMENTS
            )
            for day_offset in range(7):
                day = today + timedelta(days=day_offset)
                start_dt = datetime.combine(day, time(9, 0))
                end_dt = datetime.combine(day, time(16, 0))
                current = start_dt
                while current <= end_dt:
                    for department, provider in target_departments:
                        slots.append(
                            Slot(
                                id=str(uuid.uuid4()),
                                department=department,
                                provider=provider,
                                start_time=current,
                                is_booked=False,
                            )
                        )
                    current += timedelta(minutes=30)
            db.add_all(slots)

        db.commit()
    finally:
        db.close()
