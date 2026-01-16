from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt

from .config import settings

security = HTTPBearer(auto_error=False)

_JWKS_CACHE: dict[str, Any] | None = None
_JWKS_CACHE_EXP: float = 0.0
_JWKS_TTL_SECONDS = 3600


async def _get_jwks() -> dict[str, Any]:
    global _JWKS_CACHE, _JWKS_CACHE_EXP
    now = time.time()
    if _JWKS_CACHE and now < _JWKS_CACHE_EXP:
        return _JWKS_CACHE

    if not settings.auth0_domain:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth0 domain is not configured",
        )

    url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    _JWKS_CACHE = data
    _JWKS_CACHE_EXP = now + _JWKS_TTL_SECONDS
    return data


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict[str, Any]:
    if not settings.auth0_audience:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth0 audience is not configured",
        )

    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = credentials.credentials
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
        ) from exc

    jwks = await _get_jwks()
    keys = jwks.get("keys", [])
    rsa_key = None
    for key in keys:
        if key.get("kid") == unverified_header.get("kid"):
            rsa_key = key
            break

    if not rsa_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signing key not found",
        )

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token validation failed",
        ) from exc


def require_voice_token(x_voice_token: str | None = Header(default=None)) -> None:
    if not settings.voice_api_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Voice API token is not configured",
        )
    if not x_voice_token or x_voice_token != settings.voice_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid voice token",
        )
