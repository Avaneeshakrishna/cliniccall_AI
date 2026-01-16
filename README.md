# ClinicCall AI

ClinicCall AI is a chat-first AI receptionist that triages intent, finds nearby
providers by ZIP, suggests slots, and confirms bookings with email follow-ups.

## Features
- Intent routing: book, reschedule, cancel, urgent.
- Provider discovery via NPI Registry by ZIP (with fallback).
- Slot suggestions and confirmation flow.
- Email confirmations via SMTP.
- Lightweight chat-focused UI (voice marked as in progress).

## Tech stack
- Python, FastAPI
- SQLAlchemy + PostgreSQL
- Docker + Docker Compose
- HTML/CSS/JS (static frontend)
- OpenAI (LLM routing)
- NPI Registry API + Zippopotam ZIP lookup
- SMTP (Gmail or any SMTP provider)

## Local setup
1) Create your environment file:
   - Copy `infra/.env.example` to `infra/.env`
   - Fill in API keys and SMTP values

2) Start services:
```
cd infra
docker compose up -d --build
```

3) Open:
```
http://localhost:8000
```

## Environment variables
Required:
- `OPENAI_API_KEY`
- `DATABASE_URL`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

Optional:
- `ANTHROPIC_API_KEY`
- `ELEVENLABS_API_KEY`
- `PUBLIC_BASE_URL` (for voice webhooks)
- `ENABLE_TWILIO` (voice features)

## Demo flow
1) "I need a cardiology appointment"
2) Provide ZIP when prompted
3) Pick a provider number
4) Pick a slot number
5) Confirm (yes/no)
6) Provide phone/email if requested

## Notes
- Voice is currently marked as in progress and hidden from the UI.
- Appointment slots are generated per provider when needed.
- Conversations are stored in-memory (not persistent across restarts).

## Troubleshooting
- If emails do not send, verify SMTP credentials and rebuild the backend.
- If providers do not show, try a different ZIP (e.g., 94102, 92101).

