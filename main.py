from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None

try:
    from project.rule_engine import RuleEngine
except Exception:
    RuleEngine = None

APP_VERSION = "0.4.0"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("SENSOR_FUSION_API_KEY", "").strip()
REQUIRE_SIGNATURES = os.getenv("REQUIRE_SENSOR_SIGNATURES", "true").lower() in {"1", "true", "yes"}
INGEST_ONLY = os.getenv("INGEST_ONLY_MODE", "true").lower() in {"1", "true", "yes"}
SENSOR_KEYS_JSON = os.getenv("SENSOR_KEYS_JSON", "{}").strip() or "{}"
try:
    SENSOR_KEYS = json.loads(SENSOR_KEYS_JSON)
except json.JSONDecodeError:
    SENSOR_KEYS = {}

app = FastAPI(title="UNG Sensor Fusion", version=APP_VERSION)


@dataclass(frozen=True)
class Reading:
    source: str
    data_type: str
    value: Any
    message_id: str
    sequence: int | None
    timestamp: float


class WorldState:
    def __init__(self):
        self._lock = threading.RLock()
        self._state: dict[str, dict[str, Any]] = {}
        self._callbacks = []

    def on_update(self, callback):
        self._callbacks.append(callback)

    def update(self, reading: Reading):
        key = f"{reading.source}:{reading.data_type}"
        payload = {
            "source": reading.source,
            "data_type": reading.data_type,
            "value": reading.value,
            "message_id": reading.message_id,
            "sequence": reading.sequence,
            "timestamp": reading.timestamp,
        }
        with self._lock:
            self._state[key] = payload
        for callback in list(self._callbacks):
            try:
                callback(key, payload)
            except Exception:
                pass

    def snapshot(self):
        with self._lock:
            return dict(self._state)


world = WorldState()
_seen_lock = threading.RLock()
_seen_message_ids: set[str] = set()
_last_sequences: dict[str, int] = {}
_metrics = {"ingested": 0, "duplicates": 0, "rejected": 0}

RULES_PATH = os.path.join(os.path.dirname(__file__), "project", "rules.json")
rule_engine = RuleEngine(world, RULES_PATH, dry_run=False) if RuleEngine is not None else None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS sensor_fusion_readings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT NOT NULL,
  data_type TEXT NOT NULL,
  value_json JSONB NOT NULL,
  message_id TEXT NOT NULL UNIQUE,
  sequence BIGINT,
  sensor_timestamp DOUBLE PRECISION NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sensor_fusion_readings_recent
  ON sensor_fusion_readings(source, data_type, received_at DESC);
"""


def _db():
    if not DATABASE_URL or psycopg is None:
        return None
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


@app.on_event("startup")
def _startup():
    if DATABASE_URL and psycopg is not None:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(SCHEMA)


def _auth(x_api_key: str):
    if not API_KEY:
        raise HTTPException(503, "SENSOR_FUSION_API_KEY is not configured")
    if not hmac.compare_digest(x_api_key or "", API_KEY):
        raise HTTPException(401, "Invalid API key")


def _canonical(source: str, data_type: str, value: Any, message_id: str, sequence: int | None, timestamp: float) -> bytes:
    return json.dumps(
        {
            "source": source,
            "data_type": data_type,
            "value": value,
            "message_id": message_id,
            "sequence": sequence,
            "timestamp": timestamp,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _verify_signature(body: "IngestIn"):
    if not REQUIRE_SIGNATURES:
        return
    secret = str(SENSOR_KEYS.get(body.source, ""))
    if not secret:
        raise HTTPException(403, "Sensor identity is not registered")
    if not body.signature:
        raise HTTPException(401, "Sensor signature required")
    expected = hmac.new(
        secret.encode(),
        _canonical(body.source, body.data_type, body.value, body.message_id, body.sequence, body.timestamp),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, body.signature.lower()):
        raise HTTPException(401, "Invalid sensor signature")


class IngestIn(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    data_type: str = Field(min_length=1, max_length=128)
    value: Any
    message_id: str = Field(min_length=8, max_length=256)
    sequence: int | None = Field(default=None, ge=0)
    timestamp: float = Field(default_factory=time.time)
    signature: str | None = None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ung-sensor-fusion",
        "version": APP_VERSION,
        "ingest_only": INGEST_ONLY,
    }


@app.get("/ready")
def ready():
    db_ready = False
    if DATABASE_URL and psycopg is not None:
        try:
            with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            db_ready = True
        except Exception:
            db_ready = False
    return {
        "ready": bool(API_KEY) and (db_ready if DATABASE_URL else True),
        "api_key_configured": bool(API_KEY),
        "database_configured": bool(DATABASE_URL),
        "database_ready": db_ready,
        "sensor_signatures_required": REQUIRE_SIGNATURES,
    }


@app.get("/metrics")
def metrics(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    return {**_metrics, "state_keys": len(world.snapshot()), "rule_triggers": len(rule_engine.fired_log) if rule_engine else 0}


@app.post("/ingest")
def ingest(body: IngestIn, x_api_key: str = Header(default="")):
    _auth(x_api_key)
    try:
        _verify_signature(body)
    except HTTPException:
        _metrics["rejected"] += 1
        raise

    with _seen_lock:
        if body.message_id in _seen_message_ids:
            _metrics["duplicates"] += 1
            return {"accepted": False, "duplicate": True, "message_id": body.message_id}
        if body.sequence is not None:
            last = _last_sequences.get(body.source)
            if last is not None and body.sequence <= last:
                _metrics["duplicates"] += 1
                return {"accepted": False, "duplicate": True, "reason": "non_monotonic_sequence", "message_id": body.message_id}
            _last_sequences[body.source] = body.sequence
        _seen_message_ids.add(body.message_id)
        if len(_seen_message_ids) > 100_000:
            _seen_message_ids.clear()

    reading = Reading(
        source=body.source,
        data_type=body.data_type,
        value=body.value,
        message_id=body.message_id,
        sequence=body.sequence,
        timestamp=body.timestamp,
    )
    world.update(reading)
    _metrics["ingested"] += 1

    conn = _db()
    if conn is not None:
        with conn:
            conn.execute(
                """INSERT INTO sensor_fusion_readings(source,data_type,value_json,message_id,sequence,sensor_timestamp)
                   VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING""",
                (body.source, body.data_type, json.dumps(body.value), body.message_id, body.sequence, body.timestamp),
            )

    return {"accepted": True, "message_id": body.message_id, "state_key": f"{body.source}:{body.data_type}"}


@app.get("/state")
def state(x_api_key: str = Header(default="")):
    _auth(x_api_key)
    return world.snapshot()


@app.get("/state/{state_key:path}")
def state_one(state_key: str, x_api_key: str = Header(default="")):
    _auth(x_api_key)
    value = world.snapshot().get(state_key)
    if value is None:
        raise HTTPException(404, "State key not found")
    return value


@app.get("/events/recent")
def recent_events(limit: int = 100, x_api_key: str = Header(default="")):
    _auth(x_api_key)
    limit = max(1, min(limit, 500))
    conn = _db()
    if conn is None:
        return []
    with conn:
        rows = conn.execute(
            """SELECT source,data_type,value_json,message_id,sequence,sensor_timestamp,received_at
               FROM sensor_fusion_readings ORDER BY received_at DESC LIMIT %s""",
            (limit,),
        ).fetchall()
    return rows
