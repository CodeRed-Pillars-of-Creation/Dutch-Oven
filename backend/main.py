import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./petroguard.db')
IS_PG = DATABASE_URL.startswith(('postgresql://', 'postgres://'))

@contextmanager
def db():
    if IS_PG:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        path = DATABASE_URL.replace('sqlite:///', '', 1)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def sql(query):
    return query.replace('?', '%s') if IS_PG else query

def fetchall(cur):
    return [dict(r) for r in cur.fetchall()]

def initialize():
    with db() as conn:
        cur = conn.cursor()
        if IS_PG:
            cur.execute('''CREATE TABLE IF NOT EXISTS readings (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                worker_id TEXT NOT NULL, device_id TEXT NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                sensors_json TEXT)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS insights (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                worker_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL,
                window_name TEXT NOT NULL, content TEXT NOT NULL)''')
            cur.execute('ALTER TABLE readings ADD COLUMN IF NOT EXISTS sensors_json TEXT')
        else:
            cur.execute('''CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL,
                device_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                sensors_json TEXT)''')
            cur.execute('''CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT, worker_id TEXT NOT NULL,
                created_at TEXT NOT NULL, window_name TEXT NOT NULL, content TEXT NOT NULL)''')
            cur.execute('PRAGMA table_info(readings)')
            if 'sensors_json' not in {row[1] for row in cur.fetchall()}:
                cur.execute('ALTER TABLE readings ADD COLUMN sensors_json TEXT')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_readings_worker_time ON readings(worker_id, timestamp)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_insights_worker_time ON insights(worker_id, created_at)')

app = FastAPI(title='PetroGuard API', version='0.2.0')
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')], allow_methods=['GET', 'POST'], allow_headers=['*'])
initialize()

class ReadingIn(BaseModel):
    worker_id: str = Field(min_length=1, max_length=80)
    device_id: str = Field(min_length=1, max_length=80)
    sensors: Dict[str, Optional[float]] = Field(min_length=1, max_length=50)

    @field_validator('sensors')
    @classmethod
    def validate_sensors(cls, sensors):
        for name, value in sensors.items():
            if not name or len(name) > 80 or not all(c.isalnum() or c == '_' for c in name):
                raise ValueError('Sensor names must be 1-80 letters, digits, or underscores')
            if value is not None and not (-1e12 < value < 1e12):
                raise ValueError('Sensor readings must be finite, reasonably sized numbers or null')
        return sensors

def check_device_key(key):
    expected = os.getenv('DEVICE_API_KEY')
    if expected and key != expected:
        raise HTTPException(401, 'Invalid device key')

def serialize_row(row):
    sensors_json = row.pop('sensors_json', None)
    if sensors_json:
        row['sensors'] = json.loads(sensors_json)
    else:
        # Existing rows from the original schema remain readable.
        row['sensors'] = {name: row[name] for name in ('temperature_c', 'air_quality_raw') if name in row}
    row.pop('temperature_c', None)
    row.pop('air_quality_raw', None)
    if isinstance(row.get('timestamp'), datetime):
        row['timestamp'] = row['timestamp'].isoformat()
    return row

@app.get('/health')
def health():
    return {'status': 'ok', 'database': 'postgresql' if IS_PG else 'sqlite'}

@app.post('/readings', status_code=201)
def add_reading(reading: ReadingIn, x_device_key: Optional[str] = Header(default=None)):
    check_device_key(x_device_key)
    timestamp = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        cur = conn.cursor()
        # Legacy columns may be NOT NULL on existing databases; populate them
        # with neutral placeholders solely to satisfy the old schema. Never
        # interpret those placeholders as real measurements.
        if IS_PG:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='readings'")
            columns = {r['column_name'] for r in cur.fetchall()}
        else:
            cur.execute('PRAGMA table_info(readings)')
            columns = {r[1] for r in cur.fetchall()}
        names = ['worker_id', 'device_id', 'timestamp', 'sensors_json']
        values = [reading.worker_id, reading.device_id, timestamp, json.dumps(reading.sensors)]
        for legacy in ('temperature_c', 'air_quality_raw'):
            if legacy in columns:
                names.append(legacy)
                values.append(0.0)
        placeholders = ', '.join('?' for _ in names)
        cur.execute(sql(f"INSERT INTO readings ({', '.join(names)}) VALUES ({placeholders})"), values)
    return {'saved': True, 'timestamp': timestamp, **reading.model_dump()}

@app.get('/workers/{worker_id}/readings')
def readings(worker_id: str, limit: int = Query(100, ge=1, le=1000)):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(sql('''SELECT * FROM readings WHERE worker_id=?
            ORDER BY timestamp DESC, id DESC LIMIT ?'''), (worker_id, limit))
        return [serialize_row(row) for row in fetchall(cur)]

@app.get('/workers/{worker_id}/latest')
def latest(worker_id: str):
    rows = readings(worker_id, 1)
    if not rows:
        raise HTTPException(404, 'No readings for worker')
    return rows[0]

class AnalysisOut(BaseModel):
    short_term: str
    long_term: str
    data_limitations: str

def trend_stats(rows):
    chronological = list(reversed(rows))
    names = sorted({name for row in chronological for name in row['sensors']})
    stats = {}
    for name in names:
        available = [(r['timestamp'], r['sensors'][name]) for r in chronological
                     if r['sensors'].get(name) is not None]
        if available:
            first, last = available[0][1], available[-1][1]
            stats[name] = {'count': len(available), 'first': first, 'latest': last,
                           'change': round(last - first, 6),
                           'minimum': min(v for _, v in available),
                           'maximum': max(v for _, v in available)}
        else:
            stats[name] = {'count': 0, 'status': 'not monitored'}
    return stats

@app.post('/workers/{worker_id}/analyze')
def analyze(worker_id: str, x_device_key: Optional[str] = Header(default=None)):
    check_device_key(x_device_key)
    rows = readings(worker_id, 100)
    if not rows:
        raise HTTPException(404, 'No readings to analyze')
    if not any(value is not None for row in rows for value in row['sensors'].values()):
        raise HTTPException(422, 'No available sensor measurements to analyze')
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise HTTPException(503, 'Set GEMINI_API_KEY in .env')
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=api_key)
    stats = trend_stats(rows)
    prompt = '''You are an environmental data trend analyst generating a NON-SAFETY-CRITICAL
educational report for a student hackathon prototype. Explain the provided Python-computed
statistics and available chronological data. Only compare first vs latest values when at
least two readings exist; do not claim a meaningful trend from one reading. The entire
window may be short, so do not invent long-term, daily, or recurring patterns.

Raw UV, light, and sound sensor values are uncalibrated arbitrary units. They are NOT
UV exposure dose, lux, decibels, or regulatory exposure measurements. Never infer
chemical concentration, OSHA compliance, toxicity, hazard severity, worker safety,
PPE requirements, evacuation, or safe exposure duration. Never treat null as zero.
Industrial chemical sensor fields may be listed but null means NOT MONITORED.
If chemical sensor values ever appear, do not infer regulatory compliance or safety
without validated sensor calibration and appropriate exposure averaging periods.
Return JSON with exactly short_term, long_term, data_limitations as strings.
Short term: explain observed numeric patterns, with caveats.
Long term: describe only patterns supported by the timestamps and sample count.
Data limitations: explicitly mention unavailable measurements, calibration and
sampling limitations. Suggest qualified review for unusual changes, without making
safety decisions.

Computed statistics:\n''' + json.dumps(stats) + '\nReadings (newest first):\n' + json.dumps(rows, default=str)
    try:
        response = client.models.generate_content(
            model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'),
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json', response_schema=AnalysisOut),
        )
        result = AnalysisOut.model_validate_json(response.text).model_dump()
    except Exception as exc:
        raise HTTPException(502, f'AI analysis unavailable: {type(exc).__name__}') from exc
    timestamp = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        conn.cursor().execute(sql('''INSERT INTO insights (worker_id, created_at, window_name, content)
            VALUES (?, ?, ?, ?)'''), (worker_id, timestamp, 'recent_100_readings', json.dumps(result)))
    return {'worker_id': worker_id, 'created_at': timestamp, **result}

@app.get('/workers/{worker_id}/insights')
def insights(worker_id: str, limit: int = Query(20, ge=1, le=100)):
    with db() as conn:
        cur = conn.cursor()
        cur.execute(sql('''SELECT * FROM insights WHERE worker_id=?
            ORDER BY created_at DESC LIMIT ?'''), (worker_id, limit))
        items = fetchall(cur)
    for item in items:
        item['content'] = json.loads(item['content'])
        if isinstance(item.get('created_at'), datetime):
            item['created_at'] = item['created_at'].isoformat()
    return items
