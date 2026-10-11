"""Optional bridge: reads one JSON line per serial message and POSTs to FastAPI.
Install: pip install pyserial requests
Run: python serial_bridge.py COM3   (Windows) or /dev/ttyACM0 (Linux)
"""
import json
import os
import sys
import serial
import requests

port = sys.argv[1]
api = os.getenv('API_URL', 'http://localhost:8000/readings')
key = os.getenv('DEVICE_API_KEY', '')
with serial.Serial(port, 115200, timeout=2) as connection:
    while True:
        line = connection.readline().decode('utf-8', errors='replace').strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
            response = requests.post(api, json=payload, headers={'x-device-key': key}, timeout=10)
            response.raise_for_status()
            print('Saved:', payload)
        except (ValueError, requests.RequestException) as error:
            print('Skipped:', error, line)
