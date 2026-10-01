import json
import os
import urllib.error
import urllib.request
from typing import Any

NEXUS_BASE_URL = os.getenv("NEXUS_BASE_URL", "").rstrip("/")
NEXUS_SERVICE_TOKEN = os.getenv("NEXUS_SERVICE_TOKEN", "").strip()
MACHINE_MIND_TARGET = os.getenv("MACHINE_MIND_TARGET", "MACHINE-MIND").strip() or "MACHINE-MIND"
NEXUS_TIMEOUT = float(os.getenv("NEXUS_TIMEOUT", "3"))

def configured() -> bool:
    return bool(NEXUS_BASE_URL and NEXUS_SERVICE_TOKEN)

def publish(message_type: str, payload: dict[str, Any], *, correlation_id: str | None = None, source_system: str = "UNG-HEPHA") -> dict[str, Any]:
    if not configured():
        return {"sent": False, "reason": "nexus_not_configured"}
    body = {
        "source_system": source_system,
        "target_system": MACHINE_MIND_TARGET,
        "message_type": message_type,
        "payload": payload,
        "correlation_id": correlation_id,
        "classification": "internal",
    }
    request = urllib.request.Request(
        NEXUS_BASE_URL + "/v1/messages",
        data=json.dumps(body, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + NEXUS_SERVICE_TOKEN,
            "User-Agent": "UNG-HEPHA/machine-mind",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=NEXUS_TIMEOUT) as response:
            data = json.loads(response.read().decode() or "{}")
            return {"sent": 200 <= int(response.status) < 300, "status": int(response.status), "response": data}
    except urllib.error.HTTPError as exc:
        return {"sent": False, "status": int(exc.code), "reason": f"http_{exc.code}"}
    except Exception as exc:
        return {"sent": False, "reason": type(exc).__name__}
