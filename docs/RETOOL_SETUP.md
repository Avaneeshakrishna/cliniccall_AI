# Retool Setup

This guide shows how to call the backend endpoints from Retool, with example
queries, expected responses, and a demo flow.

Base URL:
- Local dev: `http://localhost:8000`

Auth notes:
- `GET /api/urgent_cases` and `POST /api/appointments/book` require Auth0 Bearer
  tokens. Add a header: `Authorization: Bearer <TOKEN>`.
- `POST /api/chat`, `GET /api/slots`, and `POST /api/voice/tts` are open by
  default.

## Query Examples (Retool)

### 1) List Slots
Request:
- Method: `GET`
- URL: `{{ baseUrl }}/api/slots?department={{ department }}`
- Params:
  - `department` (optional): `Dermatology` or `Cardiology`

Expected response JSON:
```json
[
  {
    "id": "uuid",
    "department": "Dermatology",
    "provider": "Dr. Patel",
    "start_time": "2026-01-15T09:00:00",
    "is_booked": false
  }
]
```

### 2) Book Appointment (protected)
Request:
- Method: `POST`
- URL: `{{ baseUrl }}/api/appointments/book`
- Headers:
  - `Content-Type: application/json`
  - `Authorization: Bearer {{ authToken }}`
- Body:
```json
{
  "patient_id": "{{ patientId }}",
  "slot_id": "{{ slotId }}",
  "reason": "{{ reason }}"
}
```

Expected response JSON:
```json
{
  "id": "uuid",
  "patient_id": "uuid",
  "slot_id": "uuid",
  "reason": "Follow-up",
  "status": "booked",
  "created_at": "2026-01-15T10:05:12.123Z"
}
```

Error example:
```json
{ "detail": "Slot already booked" }
```

### 3) Chat (routing)
Request:
- Method: `POST`
- URL: `{{ baseUrl }}/api/chat`
- Body:
```json
{
  "patient_id": "{{ patientId }}",
  "message": "I have a rash and need a visit next week"
}
```

Expected response JSON:
```json
{
  "intent": "BOOK",
  "department": "Dermatology",
  "reason": "I have a rash and need a visit next week"
}
```

### 4) TTS (text to speech)
Request:
- Method: `POST`
- URL: `{{ baseUrl }}/api/voice/tts`
- Headers:
  - `Content-Type: application/json`
- Body:
```json
{
  "text": "Hello, your appointment is confirmed.",
  "voice_id": "21m00Tcm4TlvDq8ikWAM",
  "format": "mp3"
}
```

Expected response:
- Binary audio with `Content-Type: audio/mpeg`.

Retool tips:
- For audio playback, create a temporary URL from the binary response using a
  Transformer and `URL.createObjectURL(new Blob([data], { type: "audio/mpeg" }))`.

## Demo Flow (Chat -> Slots -> Book -> Refresh)

1) `chatQuery`
- POST `/api/chat` with the patient message.
- Use `chatQuery.data.department` to filter slots.

2) `slotsQuery`
- GET `/api/slots?department={{ chatQuery.data.department }}`
- Filter out `is_booked=true` in Retool (table or transformer).

3) User selects a slot from the slots table.
- Keep selected `slot_id` in state.

4) `bookQuery`
- POST `/api/appointments/book` with `patient_id`, `slot_id`, and `reason`.

5) Refresh slots
- Run `slotsQuery` again to reflect booking updates.

## Retool Query Config Snippets

These are lightweight examples you can paste into Retool query JSON where
applicable. Adjust the `resourceName` to match your API resource.

Slots query:
```json
{
  "resourceName": "backend_api",
  "method": "GET",
  "url": "{{ baseUrl }}/api/slots",
  "queryParams": [
    { "key": "department", "value": "{{ department }}", "disabled": false }
  ]
}
```

Book appointment query (protected):
```json
{
  "resourceName": "backend_api",
  "method": "POST",
  "url": "{{ baseUrl }}/api/appointments/book",
  "headers": [
    { "key": "Content-Type", "value": "application/json" },
    { "key": "Authorization", "value": "Bearer {{ authToken }}" }
  ],
  "body": {
    "patient_id": "{{ patientId }}",
    "slot_id": "{{ slotId }}",
    "reason": "{{ reason }}"
  }
}
```

Chat query:
```json
{
  "resourceName": "backend_api",
  "method": "POST",
  "url": "{{ baseUrl }}/api/chat",
  "headers": [
    { "key": "Content-Type", "value": "application/json" }
  ],
  "body": {
    "patient_id": "{{ patientId }}",
    "message": "{{ message }}"
  }
}
```

TTS query:
```json
{
  "resourceName": "backend_api",
  "method": "POST",
  "url": "{{ baseUrl }}/api/voice/tts",
  "headers": [
    { "key": "Content-Type", "value": "application/json" }
  ],
  "body": {
    "text": "{{ ttsText }}",
    "voice_id": "{{ voiceId }}",
    "format": "mp3"
  }
}
```

## Auth0 Token Setup (for protected endpoints)

1) In Auth0, create an API and set its Identifier to your audience
   (use the same value as `AUTH0_AUDIENCE`).
2) Create a Machine-to-Machine application and authorize it for the API.
3) Generate a token using the client credentials flow:
```sh
curl -X POST https://YOUR_DOMAIN/oauth/token \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"<CLIENT_ID>\",\"client_secret\":\"<CLIENT_SECRET>\",\"audience\":\"<AUDIENCE>\",\"grant_type\":\"client_credentials\"}"
```
4) Store the `access_token` in Retool (temporary state or a secret) and pass
   it as `Authorization: Bearer {{ authToken }}` on protected queries.

## Curl Examples

List slots:
```sh
curl "http://localhost:8000/api/slots?department=Dermatology"
```

Chat routing:
```sh
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"patient_id\":\"<PATIENT_ID>\",\"message\":\"I have a rash\"}"
```

Book appointment (protected):
```sh
curl -X POST http://localhost:8000/api/appointments/book \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <TOKEN>" \
  -d "{\"patient_id\":\"<PATIENT_ID>\",\"slot_id\":\"<SLOT_ID>\",\"reason\":\"Follow-up\"}"
```

TTS:
```sh
curl -X POST http://localhost:8000/api/voice/tts \
  -H "Content-Type: application/json" \
  --output tts.mp3 \
  -d "{\"text\":\"Hello from Retool\",\"format\":\"mp3\"}"
```
