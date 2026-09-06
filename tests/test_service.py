import importlib
import json
import os
import hashlib
import hmac
import time

os.environ["SENSOR_FUSION_API_KEY"] = "test-api-key"
os.environ["SENSOR_KEYS_JSON"] = json.dumps({"s1": "sensor-secret"})
os.environ["REQUIRE_SENSOR_SIGNATURES"] = "true"

import main
importlib.reload(main)


def signed_body(**kwargs):
    body = main.IngestIn(**kwargs)
    signature = hmac.new(b"sensor-secret", main._canonical(body), hashlib.sha256).hexdigest()
    return body.model_copy(update={"signature": signature})


def test_ingest_and_dedup():
    body = signed_body(
        source="s1",
        data_type="temperature",
        value=21.5,
        message_id="message-0001",
        sequence=1,
        timestamp=time.time(),
        confidence=0.95,
        ttl_seconds=120,
    )
    first = main.ingest(body, "test-api-key")
    assert first["accepted"] is True
    assert main.ingest(body, "test-api-key")["duplicate"] is True
    state = main.state("test-api-key")["s1:temperature"]
    assert state["value"] == 21.5
    assert state["confidence"] == 0.95
    assert state["ttl_seconds"] == 120
    assert state["stale"] is False


def test_expired_state_is_marked_stale():
    body = signed_body(
        source="s1",
        data_type="pressure",
        value=101.3,
        message_id="message-0002",
        sequence=2,
        timestamp=time.time() - 10,
        confidence=0.8,
        ttl_seconds=1,
    )
    assert main.ingest(body, "test-api-key")["accepted"] is True
    state = main.state("test-api-key")["s1:pressure"]
    assert state["stale"] is True
    assert state["expires_at"] < time.time()


def test_non_monotonic_sequence_is_rejected_as_duplicate():
    body = signed_body(
        source="s1",
        data_type="humidity",
        value=50,
        message_id="message-0003",
        sequence=1,
        timestamp=time.time(),
    )
    result = main.ingest(body, "test-api-key")
    assert result["accepted"] is False
    assert result["duplicate"] is True
    assert result["reason"] == "non_monotonic_sequence"
