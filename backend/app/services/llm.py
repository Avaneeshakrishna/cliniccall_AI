import json
import logging
import time
import uuid
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI receptionist for a clinic. Extract intent/department/reason. "
    "Return JSON only."
)

INTENTS = {"BOOK", "RESCHEDULE", "CANCEL", "FAQ", "URGENT", "OTHER"}
DEPARTMENTS = {
    "Dermatology",
    "Cardiology",
    "General Medicine",
    "Pediatrics",
    "Orthopedics",
}


def _extract_first_json(text: str) -> dict[str, Any] | None:
    start = None
    depth = 0
    for idx, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start : idx + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        return None
    return None


def _normalize_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    intent = payload.get("intent")
    department = payload.get("department")
    reason = payload.get("reason")

    if isinstance(intent, str):
        intent = intent.upper()
    if intent not in INTENTS:
        return None

    if isinstance(department, str):
        department = department.title()
    if department not in DEPARTMENTS:
        department = None

    if isinstance(reason, str) and not reason.strip():
        reason = None

    return {"intent": intent, "department": department, "reason": reason}


def _fallback_route(message: str) -> dict[str, Any]:
    lowered = message.lower()
    if "cardiologist" in lowered or "cardiology" in lowered:
        return {"intent": "BOOK", "department": "Cardiology", "reason": message}
    if "chest pain" in lowered:
        return {"intent": "URGENT", "department": None, "reason": message}
    if "cardio" in lowered or "heart" in lowered:
        return {"intent": "BOOK", "department": "Cardiology", "reason": message}
    if "rash" in lowered or "skin" in lowered:
        return {"intent": "BOOK", "department": "Dermatology", "reason": message}
    if "checkup" in lowered or "general" in lowered or "primary" in lowered:
        return {"intent": "BOOK", "department": "General Medicine", "reason": message}
    if "pediatric" in lowered or "child" in lowered or "kids" in lowered:
        return {"intent": "BOOK", "department": "Pediatrics", "reason": message}
    if "ortho" in lowered or "bone" in lowered or "joint" in lowered:
        return {"intent": "BOOK", "department": "Orthopedics", "reason": message}
    return {"intent": "OTHER", "department": None, "reason": None}


async def route_message(message: str) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    used_fallback = False
    fallback_reason = None
    try:
        if not settings.anthropic_api_key:
            used_fallback = True
            fallback_reason = "missing_api_key"
            return _fallback_route(message)

        payload = {
            "model": "claude-3-5-sonnet-20240620",
            "max_tokens": 300,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": message}],
        }
        headers = {
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("content", [])
        text = "".join(
            part.get("text", "") for part in content if part.get("type") == "text"
        )
        parsed = _extract_first_json(text)
        if not isinstance(parsed, dict):
            used_fallback = True
            fallback_reason = "json_parse_failed"
            return _fallback_route(message)

        normalized = _normalize_result(parsed)
        if not normalized:
            used_fallback = True
            fallback_reason = "normalize_failed"
            return _fallback_route(message)

        return normalized
    except Exception as exc:
        used_fallback = True
        fallback_reason = f"exception:{type(exc).__name__}"
        return _fallback_route(message)
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "anthropic_route request_id=%s latency_ms=%s fallback=%s reason=%s",
            request_id,
            latency_ms,
            used_fallback,
            fallback_reason,
        )
