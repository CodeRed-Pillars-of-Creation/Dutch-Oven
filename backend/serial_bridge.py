from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone
import json
import os
import requests

HOST = "0.0.0.0"
PORT = 5000

DATA_FILE = "sensor_data.jsonl"

# FastAPI database endpoint
API_URL = os.getenv(
    "API_URL",
    "http://localhost:8000/readings"
)

# Authentication key, if required by the API
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "")


class SensorReceiver(BaseHTTPRequestHandler):

    def do_POST(self):
        # Only accept requests to the expected endpoint
        if self.path != "/":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            # Read the incoming wireless HTTP request
            length = int(self.headers.get("Content-Length", 0))

            if length <= 0:
                self.send_error(400, "Empty request body")
                return

            body = self.rfile.read(length)

            # Convert JSON text into a Python object
            data = json.loads(body.decode("utf-8"))

            # This endpoint expects one JSON object per request
            if not isinstance(data, dict):
                self.send_error(
                    400,
                    "Expected a single JSON object"
                )
                return

        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON")
            return

        # Add the laptop's UTC receipt timestamp
        data["received_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        print("Received sensor data:")
        print(json.dumps(data, indent=2))

        # Prepare database authentication
        headers = {
            "x-device-key": DEVICE_API_KEY
        }

        try:
            # Forward this individual reading to FastAPI
            response = requests.post(
                API_URL,
                json=data,
                headers=headers,
                timeout=10
            )

            # Treat non-2xx API responses as failures
            response.raise_for_status()

        except requests.RequestException as error:
            print(f"Database upload failed: {error}")

            # Tell the Arduino the reading was not confirmed
            self.send_error(
                502,
                "Database upload failed"
            )
            return

        # Save a local copy after a successful API response
        try:
            with open(DATA_FILE, "a", encoding="utf-8") as file:
                file.write(json.dumps(data) + "\n")

        except OSError as error:
            # The database may already have stored this reading
            print(f"Local file write failed: {error}")

        print("Database accepted reading.")
        print(f"API response: {response.status_code}")

        # Confirm successful database submission to the Arduino
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'{"status":"uploaded"}'
        )

    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")


server = HTTPServer((HOST, PORT), SensorReceiver)

print(f"Listening for Arduino data on port {PORT}...")
print(f"Database endpoint: {API_URL}")
print(f"Local backup file: {DATA_FILE}")

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\\nReceiver stopped.")
finally:
    server.server_close()
