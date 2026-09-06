import importlib
import json
import os
import hashlib
import hmac

os.environ["SENSOR_FUSION_API_KEY"] = "test-api-key"
os.environ["SENSOR_KEYS_JSON"] = json.dumps({"s1": "sensor-secret"})
os.environ["REQUIRE_SENSOR_SIGNATURES"] = "true"

import main
importlib.reload(main)


def sig(payload):
    raw = main._canonical(payload["source"], payload["data_type"], payload["value"], payload["message_id"], payload.get("sequence"), payload["timestamp"])
    return hmac.new(b"sensor-secret", raw, hashlib.sha256).hexdigest()


def test_ingest_and_dedup():
    p = {"source":"s1","data_type":"temperature","value":21.5,"message_id":"message-0001","sequence":1,"timestamp":1.0}
    body = main.IngestIn(**p, signature=sig(p))
    assert main.ingest(body, "test-api-key")["accepted"] is True
    assert main.ingest(body, "test-api-key")["duplicate"] is True
    assert main.state("test-api-key")["s1:temperature"]["value"] == 21.5
