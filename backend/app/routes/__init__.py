from fastapi import APIRouter

from .appointments import router as appointments_router
from .chat import router as chat_router
from .patients import router as patients_router
from .slots import router as slots_router
from .triage import router as triage_router
from .voice import router as voice_router

api_router = APIRouter()
api_router.include_router(slots_router)
api_router.include_router(appointments_router)
api_router.include_router(chat_router)
api_router.include_router(patients_router)
api_router.include_router(triage_router)
api_router.include_router(voice_router)
