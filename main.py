from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from contextlib import asynccontextmanager
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

APP_VERSION = "0.5.0"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
API_KEY = os.getenv("SENSOR_FUSION_API_KEY", "").strip()
REQUIRE_SIGNATURES = os.getenv("REQUIRE_SENSOR_SIGNATURES", "true").lower() in {"1", "true", "yes"}
INGEST_ONLY = os.getenv("INGEST_ONLY_MODE", "true").lower() in {"1", "true", "yes"}
SENSOR_KEYS_JSON = os.getenv("SENSOR_KEYS_JSON", "{}").strip() or "{}"
try:
    SENSOR_KEYS = json.loads(SENSOR_KEYS_JSON)
except json.JSONDecodeError:
    SENSOR_KEYS = {}

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS sensor_fusion_readings (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), source TEXT NOT NULL, data_type TEXT NOT NULL,
 value_json JSONB NOT NULL, message_id TEXT NOT NULL UNIQUE, sequence BIGINT,
 sensor_timestamp DOUBLE PRECISION NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_sensor_fusion_readings_recent ON sensor_fusion_readings(source,data_type,received_at DESC);
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_URL and psycopg is not None:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(SCHEMA)
    yield

app = FastAPI(title="UNG Sensor Fusion", version=APP_VERSION, lifespan=lifespan)

@dataclass(frozen=True)
class Reading:
    source: str; data_type: str; value: Any; message_id: str; sequence: int | None; timestamp: float
    confidence: float; ttl_seconds: int

class WorldState:
    def __init__(self):
        self._lock=threading.RLock(); self._state={}; self._callbacks=[]
    def on_update(self, callback): self._callbacks.append(callback)
    def update(self, r: Reading):
        key=f"{r.source}:{r.data_type}"
        payload={"source":r.source,"data_type":r.data_type,"value":r.value,"message_id":r.message_id,
                 "sequence":r.sequence,"timestamp":r.timestamp,"confidence":r.confidence,"ttl_seconds":r.ttl_seconds,
                 "expires_at":r.timestamp+r.ttl_seconds}
        with self._lock: self._state[key]=payload
        for cb in list(self._callbacks):
            try: cb(key,payload)
            except Exception: pass
    def snapshot(self):
        now=time.time()
        with self._lock:
            return {k:{**v,"stale":now>v["expires_at"]} for k,v in self._state.items()}

world=WorldState(); _seen_lock=threading.RLock(); _seen_message_ids=set(); _last_sequences={}
_metrics={"ingested":0,"duplicates":0,"rejected":0}
RULES_PATH=os.path.join(os.path.dirname(__file__),"project","rules.json")
rule_engine=RuleEngine(world,RULES_PATH,dry_run=False) if RuleEngine is not None else None

def _db():
    if not DATABASE_URL or psycopg is None: return None
    return psycopg.connect(DATABASE_URL,row_factory=dict_row)

def _auth(key:str):
    if not API_KEY: raise HTTPException(503,"SENSOR_FUSION_API_KEY is not configured")
    if not hmac.compare_digest(key or "",API_KEY): raise HTTPException(401,"Invalid API key")

def _canonical(b):
    return json.dumps({"source":b.source,"data_type":b.data_type,"value":b.value,"message_id":b.message_id,
                       "sequence":b.sequence,"timestamp":b.timestamp},sort_keys=True,separators=(",",":")).encode()

def _verify_signature(b):
    if not REQUIRE_SIGNATURES: return
    secret=str(SENSOR_KEYS.get(b.source,""))
    if not secret: raise HTTPException(403,"Sensor identity is not registered")
    if not b.signature: raise HTTPException(401,"Sensor signature required")
    expected=hmac.new(secret.encode(),_canonical(b),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,b.signature.lower()): raise HTTPException(401,"Invalid sensor signature")

class IngestIn(BaseModel):
    source:str=Field(min_length=1,max_length=128); data_type:str=Field(min_length=1,max_length=128); value:Any
    message_id:str=Field(min_length=8,max_length=256); sequence:int|None=Field(default=None,ge=0)
    timestamp:float=Field(default_factory=time.time); signature:str|None=None
    confidence:float=Field(default=1.0,ge=0.0,le=1.0); ttl_seconds:int=Field(default=120,ge=1,le=86400)

@app.get('/health')
def health(): return {"status":"ok","service":"ung-sensor-fusion","version":APP_VERSION,"ingest_only":INGEST_ONLY}

@app.get('/ready')
def ready():
    db_ready=False
    if DATABASE_URL and psycopg is not None:
        try:
            with psycopg.connect(DATABASE_URL,connect_timeout=3) as c: c.execute("SELECT 1")
            db_ready=True
        except Exception: pass
    return {"ready":bool(API_KEY) and (db_ready if DATABASE_URL else True),"api_key_configured":bool(API_KEY),
            "database_configured":bool(DATABASE_URL),"database_ready":db_ready,"sensor_signatures_required":REQUIRE_SIGNATURES}

@app.get('/metrics')
def metrics(x_api_key:str=Header(default="")):
    _auth(x_api_key); return {**_metrics,"state_keys":len(world.snapshot()),"rule_triggers":len(rule_engine.fired_log) if rule_engine else 0}

@app.post('/ingest')
def ingest(body:IngestIn,x_api_key:str=Header(default="")):
    _auth(x_api_key)
    try: _verify_signature(body)
    except HTTPException: _metrics["rejected"]+=1; raise
    with _seen_lock:
        if body.message_id in _seen_message_ids:
            _metrics["duplicates"]+=1; return {"accepted":False,"duplicate":True,"message_id":body.message_id}
        if body.sequence is not None:
            last=_last_sequences.get(body.source)
            if last is not None and body.sequence<=last:
                _metrics["duplicates"]+=1; return {"accepted":False,"duplicate":True,"reason":"non_monotonic_sequence","message_id":body.message_id}
            _last_sequences[body.source]=body.sequence
        _seen_message_ids.add(body.message_id)
        if len(_seen_message_ids)>100000: _seen_message_ids.clear()
    r=Reading(body.source,body.data_type,body.value,body.message_id,body.sequence,body.timestamp,body.confidence,body.ttl_seconds)
    world.update(r); _metrics["ingested"]+=1
    c=_db()
    if c is not None:
        with c: c.execute("INSERT INTO sensor_fusion_readings(source,data_type,value_json,message_id,sequence,sensor_timestamp) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO NOTHING",(body.source,body.data_type,json.dumps(body.value),body.message_id,body.sequence,body.timestamp))
    return {"accepted":True,"message_id":body.message_id,"state_key":f"{body.source}:{body.data_type}","expires_at":body.timestamp+body.ttl_seconds}

@app.get('/state')
def state(x_api_key:str=Header(default="")): _auth(x_api_key); return world.snapshot()
@app.get('/state/{state_key:path}')
def state_one(state_key:str,x_api_key:str=Header(default="")):
    _auth(x_api_key); value=world.snapshot().get(state_key)
    if value is None: raise HTTPException(404,"State key not found")
    return value
@app.get('/events/recent')
def recent_events(limit:int=100,x_api_key:str=Header(default="")):
    _auth(x_api_key); limit=max(1,min(limit,500)); c=_db()
    if c is None: return []
    with c: return c.execute("SELECT source,data_type,value_json,message_id,sequence,sensor_timestamp,received_at FROM sensor_fusion_readings ORDER BY received_at DESC LIMIT %s",(limit,)).fetchall()
