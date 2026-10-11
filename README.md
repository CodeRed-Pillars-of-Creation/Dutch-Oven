# PetroGuard Sensor Dashboard

PetroGuard collects sensor readings from an Arduino, forwards them through a Python HTTP receiver, stores them through a FastAPI backend, and displays them in an HTML dashboard.

This README describes the local development setup discussed for the current project. Check the notes under **Troubleshooting** if your local files differ from the paths or sensor field names described here.

## Architecture

```text
Arduino
  |
  | HTTP POST to http://<laptop-ip>:5000/
  v
serial_bridge.py  (Python HTTP receiver)
  |
  | HTTP POST to http://localhost:8000/readings
  v
FastAPI backend (main.py)
  |
  v
SQLite database (petroguard.db by default)

Browser
  |
  | Opens the HTML dashboard from port 5500
  | Dashboard fetches readings from port 8000
  v
FastAPI: GET /workers/{worker_id}/readings
```

The receiver listens on port `5000`. The API listens on port `8000`. The static HTML server listens on port `5500`.

## Project files

- `main.py` — FastAPI backend, database initialization, and reading/insight endpoints.
- `requirements.txt` — Python dependencies for the backend.
- `serial_bridge.py` — HTTP receiver for Arduino requests; forwards readings to FastAPI and appends successful readings to `sensor_data.jsonl`.
- `inProgress_database.html` — HTML dashboard configured to retrieve readings from the FastAPI backend.
- `petroguard.db` — SQLite database file created by the backend by default.
- `sensor_data.jsonl` — local JSON Lines backup written by the receiver after a successful API upload.

The filename `serial_bridge.py` is historical: the current script is an HTTP receiver, not a serial-port reader.

## Requirements

- Python 3.10 or newer is recommended.
- The Arduino and laptop must be connected to a network that allows the Arduino to reach the laptop.
- The dashboard can be served with Python's built-in HTTP server.
- The backend uses SQLite by default, so PostgreSQL is not required for local development.

## 1. Set up the backend

Open a terminal in the directory containing `main.py` and `requirements.txt`.

### Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use Command Prompt instead:

```bat
.venv\Scripts\activate.bat
```

### Install dependencies

```powershell
python -m pip install -r requirements.txt
python -m pip install requests
```

`requests` is required by `serial_bridge.py`. It is installed separately because it is not currently listed in the supplied `requirements.txt`.

### Configure environment variables

Create a `.env` file in the backend directory if you need to customize the settings. For local development, the following CORS setting allows the dashboard served from either local hostname:

```dotenv
CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
```

The backend uses SQLite by default at `sqlite:///./petroguard.db`. You can optionally set `DATABASE_URL` to use a configured PostgreSQL database.

If you configure `DEVICE_API_KEY`, the receiver and backend must use the same value. For example, add this to the backend `.env`:

```dotenv
DEVICE_API_KEY=replace-with-a-long-random-secret
```

Then set the same `DEVICE_API_KEY` in the environment used to launch `serial_bridge.py`. If `DEVICE_API_KEY` is not configured on the backend, the current backend implementation does not require a key; do not expose that configuration to untrusted networks.

### Start the backend

From the backend directory, with the virtual environment activated:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Keep this terminal open.

Check the health endpoint in a browser:

- `http://localhost:8000/health`
- `http://localhost:8000/docs` — interactive API documentation

The health endpoint should return a status of `ok` and identify the configured database.

## 2. Start the Arduino HTTP receiver

Open a second terminal in the directory containing `serial_bridge.py`.

Activate the same virtual environment if you are using one:

```powershell
.\.venv\Scripts\Activate.ps1
```

Start the receiver:

```powershell
python serial_bridge.py
```

It should report that it is listening on port `5000` and show the configured FastAPI destination, normally:

```text
http://localhost:8000/readings
```

The receiver accepts **HTTP POST requests to `/`**. The Arduino should therefore send data to:

```text
http://<laptop-ip>:5000/
```

Replace `<laptop-ip>` with the laptop's LAN IP address. Do not use `localhost` in the Arduino URL: from the Arduino's perspective, `localhost` would refer to the Arduino itself.

The receiver forwards each request to FastAPI at `http://localhost:8000/readings`. The receiver accepts one JSON object per HTTP request, not a JSON array of readings.

### Expected reading structure

The backend expects each reading to contain:

```json
{
  "worker_id": "worker_001",
  "device_id": "arduino_001",
  "sensors": {
    "uv_raw": 320,
    "light_raw": 450,
    "sound_raw": 210,
    "hydrogen_sulfide_ppm": null,
    "carbon_monoxide_ppm": null,
    "benzene_ppm": null,
    "oxygen_percent": null
  }
}
```

This is an example schema. Use the exact sensor field names and units produced by your Arduino. Sensor values can be numbers or `null`. `worker_id`, `device_id`, and the nested `sensors` object are required by the backend.

The backend generates its own `timestamp` when it stores a reading. The receiver also adds `received_at` before forwarding the JSON; the current backend may ignore that extra field.

## 3. Start the HTML dashboard

Open a third terminal in the directory containing `inProgress_database.html`.

Start a static web server:

```powershell
python -m http.server 5500
```

Open:

```text
http://localhost:5500/inProgress_database.html
```

The dashboard's API configuration should point to the FastAPI backend, not to the static-file server. The expected local configuration is:

```javascript
const API = {
  baseUrl: "http://localhost:8000",
  pollMs: 5000
};
```

Its reading URL should use the backend endpoint:

```text
http://localhost:8000/workers/worker_001/readings?limit=500
```

The dashboard's `WORKER_ID` must match the `worker_id` sent by the Arduino. The dashboard's sensor-field mapping must also match the actual keys inside the backend response's `sensors` object.

## 4. Verify the data flow

1. Start FastAPI and confirm `http://localhost:8000/health` works.
2. Start `serial_bridge.py`.
3. Start the HTML server and open the dashboard.
4. Send a reading from the Arduino.
5. Confirm the receiver logs the reading and then reports that the database accepted it.
6. Open `http://localhost:8000/docs` and test `GET /workers/worker_001/readings?limit=10`, or visit the equivalent URL directly in the browser.
7. Confirm the reading appears on the dashboard.

You can also use the interactive documentation at `/docs` to test `POST /readings` with the example JSON above. This tests the backend independently of the Arduino and receiver.

## API endpoints used by the dashboard

- `GET /health` — backend and database health check.
- `POST /readings` — store one reading.
- `GET /workers/{worker_id}/readings?limit=100` — retrieve readings for a worker.
- `GET /workers/{worker_id}/latest` — retrieve the latest reading for a worker.
- `GET /workers/{worker_id}/insights` — retrieve saved insights.
- `POST /workers/{worker_id}/analyze` — run analysis; this requires `GEMINI_API_KEY` and is not needed for basic ingestion or dashboard display.

The backend's reading endpoint is `/workers/{worker_id}/readings`, not `/api/readings`.

## Troubleshooting

### `ModuleNotFoundError: No module named 'requests'`

Install `requests` into the same Python environment used to run the receiver:

```powershell
python -m pip install requests
```

If using a virtual environment, activate it first.

### Receiver reports `[HTTP] 404` for `POST /sensor`

The receiver only accepts `POST /`. Make sure the Arduino sends to `http://<laptop-ip>:5000/`, or deliberately change the receiver's path check to accept `/sensor`. The Arduino path and receiver path must match.

### Browser/static server reports 404 for `/api/readings`

The Python static-file server does not implement `/api/readings`; it treats the URL as a file request. Find and update any remaining `/api/readings` references in the HTML or JavaScript. The dashboard should fetch readings from FastAPI on port `8000` using `/workers/{worker_id}/readings?limit=...`.

If readings display correctly but this old 404 continues, an obsolete request may still be running in another script, an older cached copy of the page may be loaded, or the page may contain another polling function. Search the active HTML file for `/api/readings`, then hard-refresh the browser with `Ctrl+Shift+R`. The browser Developer Tools Network tab can show which script initiated the request.

### FastAPI returns `422 Unprocessable Entity`

The JSON does not match the backend model. Confirm that each POST contains:
- `worker_id` as a non-empty string.
- `device_id` as a non-empty string.
- `sensors` as an object whose values are numeric or `null`.

### Receiver reports `502 Database upload failed`

The receiver could not complete the POST to FastAPI. Confirm that the backend is running at `http://localhost:8000`, that `API_URL` is correct, and that the receiver's printed error explains the underlying HTTP or connection failure. A backend `422` or `500` response will also cause the receiver to report a failed upload.

### Dashboard opens but does not show readings

- Check that `WORKER_ID` matches the Arduino's `worker_id`.
- Check that the dashboard requests port `8000`, not port `5500`, for data.
- Check CORS settings if the browser console reports a cross-origin error.
- Check that the frontend sensor-field mapping matches the actual `sensors` keys returned by FastAPI.
- Inspect the browser Developer Tools Console and Network tabs for failed requests.

## Access from another device

For another device on the same LAN to view the dashboard, the dashboard must use the laptop's LAN IP address instead of `localhost` for the API URL. The backend must listen on an address reachable over the LAN (for example, `0.0.0.0`), and the laptop firewall must permit the required port. Configure `CORS_ORIGINS` to include the exact dashboard origin used by the other device.

Only do this on a trusted network with appropriate authentication and firewall rules. Do not expose the development API or receiver directly to the public internet without suitable security controls.

## Notes

- `sensor_data.jsonl` is a local backup, not the dashboard's data source. The dashboard should retrieve readings from FastAPI.
- SQLite database paths are relative to the backend process's working directory. Start Uvicorn from the backend directory to keep `petroguard.db` in the expected location.
- AI analysis is optional for the basic data collection and dashboard workflow; it requires `GEMINI_API_KEY`.
