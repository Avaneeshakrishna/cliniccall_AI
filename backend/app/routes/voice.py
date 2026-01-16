import base64
import io
import json
import logging
import time
import wave
from datetime import datetime

import audioop
import httpx

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from ..config import settings
from ..services.voice import synthesize_speech, transcribe_audio

router = APIRouter()
_voice_sessions: dict[str, dict] = {}
logger = logging.getLogger("uvicorn.error")


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None
    format: str = "mp3"


@router.post("/voice/tts")
async def tts(payload: TTSRequest) -> Response:
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")
    try:
        audio_bytes, content_type = await synthesize_speech(
            text=payload.text,
            voice_id=payload.voice_id or "21m00Tcm4TlvDq8ikWAM",
            audio_format=payload.format,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="TTS provider error")
    return Response(content=audio_bytes, media_type=content_type)


@router.post("/voice/transcribe")
async def voice_transcribe(file: UploadFile = File(...)) -> dict:
    if not file:
        raise HTTPException(status_code=400, detail="Audio file is required")
    try:
        audio_bytes = await file.read()
        filename = file.filename or "audio.webm"
        content_type = file.content_type or "application/octet-stream"
        text = await transcribe_audio(
            audio_bytes,
            filename=filename,
            content_type=content_type,
            prompt="Medical appointment scheduling, departments: Dermatology, Cardiology, General Medicine, Pediatrics, Orthopedics.",
        )
        return {"text": text}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "stt_provider_error status=%s body=%s",
            exc.response.status_code,
            exc.response.text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"STT provider error ({exc.response.status_code})",
        ) from exc
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="STT provider error")


def _twiml_response(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _ensure_twilio_enabled() -> None:
    if not settings.enable_twilio:
        raise HTTPException(
            status_code=503,
            detail="Twilio voice endpoints are disabled",
        )


def _public_url(path: str) -> str:
    base = settings.public_base_url.rstrip("/")
    if not base:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    return f"{base}{path}"


def _public_ws_url(path: str) -> str:
    base = settings.public_base_url.rstrip("/")
    if not base:
        raise RuntimeError("PUBLIC_BASE_URL is not configured")
    if base.startswith("https://"):
        base = f"wss://{base[len('https://'):]}"
    elif base.startswith("http://"):
        base = f"ws://{base[len('http://'):]}"
    return f"{base}{path}"


def _format_slot_time(start_time: str | None) -> str:
    if not start_time:
        return "unknown time"
    if start_time.endswith("Z"):
        start_time = start_time.replace("Z", "+00:00")
    dt = datetime.fromisoformat(start_time)
    return dt.strftime("%A %I:%M %p").lstrip("0")


def _mulaw_to_wav(mulaw_bytes: bytes) -> bytes:
    pcm = audioop.ulaw2lin(mulaw_bytes, 2)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


@router.post("/voice/inbound")
async def voice_inbound(request: Request) -> Response:
    _ensure_twilio_enabled()
    form = await request.form()
    call_sid = form.get("CallSid")
    from_number = form.get("From", "")
    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    _voice_sessions[call_sid] = {
        "from": from_number,
        "created_at": time.time(),
        "transcript": None,
        "chat": None,
        "slots": None,
        "polls": 0,
        "error": None,
        "media": bytearray(),
        "media_bytes": 0,
    }

    try:
        ws_url = _public_ws_url(f"/api/voice/stream?call_sid={call_sid}")
        result_url = _public_url(f"/api/voice/result?call_sid={call_sid}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Thanks for calling. Please tell me how I can help you today.</Say>
  <Start>
    <Stream url="{ws_url}" track="inbound">
      <Parameter name="from" value="{from_number}" />
    </Stream>
  </Start>
  <Pause length="20" />
  <Redirect method="POST">{result_url}</Redirect>
</Response>
"""
    return _twiml_response(twiml)


@router.websocket("/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    if not settings.enable_twilio:
        await websocket.close()
        return
    await websocket.accept()
    call_sid = websocket.query_params.get("call_sid")
    if not call_sid:
        await websocket.close()
        return

    session = _voice_sessions.setdefault(
        call_sid, {"media": bytearray(), "polls": 0, "created_at": time.time()}
    )
    buffer = session.setdefault("media", bytearray())
    print(f"voice_stream_connected call_sid={call_sid}")

    try:
        while True:
            message = await websocket.receive()
            logger.warning(
                "voice_stream_receive call_sid=%s keys=%s",
                call_sid,
                list(message.keys()),
            )
            print(f"voice_stream_receive call_sid={call_sid} keys={list(message.keys())}")
            raw = message.get("text")
            if raw is None and message.get("bytes") is not None:
                try:
                    raw = message["bytes"].decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning("voice_stream_decode_failed call_sid=%s", call_sid)
                    continue
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("voice_stream_json_failed call_sid=%s", call_sid)
                continue
            event = payload.get("event")
            if event == "start":
                start = payload.get("start", {})
                call_sid = start.get("callSid", call_sid)
                session["call_sid"] = call_sid
                custom = start.get("customParameters", {})
                if custom.get("from"):
                    session["from"] = custom["from"]
                logger.warning("voice_stream_start call_sid=%s", call_sid)
            elif event == "media":
                media = payload.get("media", {})
                chunk = media.get("payload")
                if chunk:
                    decoded = base64.b64decode(chunk)
                    buffer.extend(decoded)
                    session["media_bytes"] = session.get("media_bytes", 0) + len(decoded)
            elif event == "stop":
                logger.warning(
                    "voice_stream_stop call_sid=%s media_bytes=%s",
                    call_sid,
                    session.get("media_bytes", 0),
                )
                break
    except WebSocketDisconnect:
        print(f"voice_stream_disconnect call_sid={call_sid}")
        pass
    finally:
        try:
            if buffer:
                wav_bytes = _mulaw_to_wav(bytes(buffer))
                transcript = await transcribe_audio(
                    wav_bytes,
                    filename="audio.wav",
                    content_type="audio/wav",
                    prompt="Medical appointment scheduling, departments: Dermatology, Cardiology, General Medicine, Pediatrics, Orthopedics.",
                )
                session["transcript"] = transcript
            if not session.get("media_bytes"):
                logger.warning("voice_stream_no_audio call_sid=%s", call_sid)
        except Exception as exc:
            logger.warning("voice_stream_error call_sid=%s error=%s", call_sid, exc)
            session["error"] = str(exc)


@router.post("/voice/result")
async def voice_result(request: Request) -> Response:
    _ensure_twilio_enabled()
    form = await request.form()
    call_sid = request.query_params.get("call_sid") or form.get("CallSid")
    if not call_sid or call_sid not in _voice_sessions:
        raise HTTPException(status_code=400, detail="Unknown CallSid")

    session = _voice_sessions[call_sid]
    print(
        f"voice_result_poll call_sid={call_sid} media_bytes={session.get('media_bytes', 0)} "
        f"transcript_len={len(session.get('transcript') or '')}"
    )
    logger.warning(
        "voice_result_poll call_sid=%s media_bytes=%s transcript_len=%s",
        call_sid,
        session.get("media_bytes", 0),
        len(session.get("transcript") or ""),
    )
    if session.get("error"):
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, I am having trouble understanding the audio. Please try again later.</Say>
  <Hangup />
</Response>
"""
        return _twiml_response(twiml)

    if not session.get("transcript"):
        session["polls"] = session.get("polls", 0) + 1
        if session["polls"] > 6:
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, I could not process that in time. Please call back.</Say>
  <Hangup />
</Response>
"""
            return _twiml_response(twiml)

        try:
            result_url = _public_url(f"/api/voice/result?call_sid={call_sid}")
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>One moment while I process that.</Say>
  <Pause length="4" />
  <Redirect method="POST">{result_url}</Redirect>
</Response>
"""
        return _twiml_response(twiml)

    if not session.get("chat"):
        chat_url = f"{settings.internal_api_base_url.rstrip('/')}/api/chat"
        payload = {"message": session["transcript"]}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(chat_url, json=payload)
            response.raise_for_status()
            session["chat"] = response.json()

    chat = session["chat"]
    intent = chat.get("intent")
    reply = chat.get("reply") or "Thanks for calling."

    if intent == "BOOK" and chat.get("suggested_slots"):
        slots = chat["suggested_slots"][:3]
        session["slots"] = slots
        option_lines = []
        for idx, slot in enumerate(slots, start=1):
            time_label = _format_slot_time(slot.get("start_time"))
            department = slot.get("department", "the clinic")
            option_lines.append(f"Press {idx} for {department} at {time_label}.")

        try:
            confirm_url = _public_url(f"/api/voice/confirm?call_sid={call_sid}")
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        say_text = " ".join([reply, *option_lines, "Press a number now."])
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Gather numDigits="1" action="{confirm_url}" method="POST">
    <Say>{say_text}</Say>
  </Gather>
  <Say>I did not receive a selection. Goodbye.</Say>
  <Hangup />
</Response>
"""
        return _twiml_response(twiml)

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>{reply}</Say>
  <Hangup />
</Response>
"""
    return _twiml_response(twiml)


@router.post("/voice/confirm")
async def voice_confirm(request: Request) -> Response:
    _ensure_twilio_enabled()
    form = await request.form()
    call_sid = request.query_params.get("call_sid") or form.get("CallSid")
    digits = form.get("Digits")
    if not call_sid or call_sid not in _voice_sessions:
        raise HTTPException(status_code=400, detail="Unknown CallSid")

    session = _voice_sessions[call_sid]
    slots = session.get("slots") or []
    if not digits or not digits.isdigit():
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>I did not get a valid selection. Please call back to try again.</Say>
  <Hangup />
</Response>
"""
        return _twiml_response(twiml)

    index = int(digits) - 1
    if index < 0 or index >= len(slots):
        twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>That selection is not available. Please call back and try again.</Say>
  <Hangup />
</Response>
"""
        return _twiml_response(twiml)

    if not settings.voice_api_token:
        raise HTTPException(status_code=500, detail="VOICE_API_TOKEN is not configured")

    slot = slots[index]
    reason = (session.get("chat") or {}).get("reason") or "Voice booking"
    phone = session.get("from") or ""
    payload = {"phone": phone, "slot_id": slot.get("id"), "reason": reason}

    book_url = f"{settings.internal_api_base_url.rstrip('/')}/api/appointments/voice-book"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            book_url,
            json=payload,
            headers={"X-Voice-Token": settings.voice_api_token},
        )
        if response.status_code >= 400:
            twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Sorry, I could not book that appointment. Please try again later.</Say>
  <Hangup />
</Response>
"""
            return _twiml_response(twiml)

    time_label = _format_slot_time(slot.get("start_time"))
    department = slot.get("department", "the clinic")
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>Your appointment for {department} at {time_label} is booked. We will text a confirmation.</Say>
  <Hangup />
</Response>
"""
    return _twiml_response(twiml)
