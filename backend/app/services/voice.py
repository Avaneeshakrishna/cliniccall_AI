import logging
import time
import uuid

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def synthesize_speech(
    text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM", audio_format: str = "mp3"
) -> tuple[bytes, str]:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        }
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "output_format": "mp3_44100_128",
        }
        if audio_format != "mp3":
            payload["output_format"] = audio_format

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.content, "audio/mpeg"
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "elevenlabs_tts request_id=%s latency_ms=%s",
            request_id,
            latency_ms,
        )


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "audio.wav",
    content_type: str = "audio/wav",
    prompt: str | None = None,
) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    request_id = uuid.uuid4().hex
    start = time.perf_counter()
    try:
        url = f"{settings.openai_base_url.rstrip('/')}/audio/transcriptions"
        headers = {"authorization": f"Bearer {settings.openai_api_key}"}
        files = {"file": (filename, audio_bytes, content_type)}
        data = {"model": "whisper-1", "language": "en"}
        if prompt:
            data["prompt"] = prompt

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            payload = response.json()
        text = payload.get("text", "")
        return text.strip()
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "openai_transcribe request_id=%s latency_ms=%s",
            request_id,
            latency_ms,
        )
