# PetroGuard backend — hackathon MVP

## Run locally

1. Install Python 3.10+.
2. `python -m venv .venv` and activate it.
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`; set `DEVICE_API_KEY` and `GEMINI_API_KEY`.
5. `uvicorn main:app --reload`
6. Open `http://localhost:8000/docs` for interactive API testing.

SQLite works by default. To use Tiger Data, replace `DATABASE_URL` with the PostgreSQL URL provided by Tiger Data and restart the app. The app creates tables on startup. Use a database account authorized to create tables.

## Sample POST from hardware bridge

```bash
curl -X POST http://localhost:8000/readings \
  -H 'Content-Type: application/json' \
  -H 'x-device-key: change-this-before-deploying' \
  -d '{"worker_id":"worker_001","device_id":"pico_001","temperature_c":31.5,"air_quality_raw":420}'
```

## Frontend contract

- `GET /workers/worker_001/latest`
- `GET /workers/worker_001/readings?limit=100`
- `POST /workers/worker_001/analyze` (send `x-device-key` header; trigger from trusted server code, not public browser)
- `GET /workers/worker_001/insights`

`POST /readings` also requires the device key. For the hackathon, GET endpoints are open; **do not deploy with real worker data** without user authentication, access controls, TLS, consent, retention rules, and security review. Never expose your device key or Gemini key in frontend JavaScript.

## Hardware serial format

Have the microcontroller print one complete JSON object per line at 115200 baud, e.g.:

```json
{"worker_id":"worker_001","device_id":"pico_001","temperature_c":31.5,"air_quality_raw":420}
```

If it sends serial data rather than HTTP, install `pip install pyserial requests`, set `DEVICE_API_KEY`, and run `python serial_bridge.py /dev/ttyACM0` (replace with your actual port). Match the real sensor's units and protocol before integrating.

## Important limitations

Generic Grove air-quality sensors are not validated chemical-specific personal exposure monitors. AI outputs are educational summaries only. Do not use this prototype to prescribe PPE, determine safe shift durations, or assess regulatory compliance. Test with synthetic data until sensor model and calibration are confirmed.
