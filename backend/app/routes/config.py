from fastapi import APIRouter

from ..config import settings

router = APIRouter()


@router.get("/config")
def get_config() -> dict:
    return {
        "auth0_domain": settings.auth0_domain,
        "auth0_audience": settings.auth0_audience,
        "auth0_client_id": settings.auth0_client_id,
    }
