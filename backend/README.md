# AI Receptionist Backend

Quick curl examples (unit-like sanity checks):

```sh
curl http://localhost:8000/health
```

```sh
curl "http://localhost:8000/api/slots?department=Dermatology"
```

```sh
curl -X POST http://localhost:8000/api/appointments/book \
  -H "Content-Type: application/json" \
  -d "{\"patient_id\":\"<PATIENT_ID>\",\"slot_id\":\"<SLOT_ID>\",\"reason\":\"Follow-up\"}"
```
