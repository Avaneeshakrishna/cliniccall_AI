import json
import logging
import time
import uuid
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an AI receptionist for a clinic. Extract triage severity, summary, "
    "and whether to escalate. Return JSON only."
)

SEVERITIES = {"EMERGENCY", "URGENT", "ROUTINE"}


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
    severity = payload.get("severity")
    summary = payload.get("summary")
    escalate = payload.get("escalate")

    if isinstance(severity, str):
        severity = severity.upper()
    if severity not in SEVERITIES:
        return None

    if not isinstance(summary, str) or not summary.strip():
        summary = "Triage summary unavailable."

    if not isinstance(escalate, bool):
        escalate = severity != "ROUTINE"

    return {"severity": severity, "summary": summary, "escalate": escalate}


def _fallback_triage(message: str) -> dict[str, Any]:
    lowered = message.lower()
    if "chest pain" in lowered or "shortness of breath" in lowered:
        return {
            "severity": "EMERGENCY",
            "summary": "Possible cardiac or respiratory emergency symptoms.",
            "escalate": True,
        }
    if "bleeding" in lowered or "severe pain" in lowered:
        return {
            "severity": "URGENT",
            "summary": "Potentially urgent symptoms reported.",
            "escalate": True,
        }
    return {
        "severity": "ROUTINE",
        "summary": "No urgent indicators detected.",
        "escalate": False,
    }


async def triage_message(message: str) -> dict[str, Any]:
    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    used_fallback = False
    try:
        if not settings.anthropic_api_key:
            used_fallback = True
            return _fallback_triage(message)

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
            return _fallback_triage(message)

        normalized = _normalize_result(parsed)
        if not normalized:
            used_fallback = True
            return _fallback_triage(message)

        return normalized
    except Exception:
        used_fallback = True
        return _fallback_triage(message)
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "triage_route request_id=%s latency_ms=%s fallback=%s",
            request_id,
            latency_ms,
            used_fallback,
        )
