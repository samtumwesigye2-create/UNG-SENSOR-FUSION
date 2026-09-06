"""
Rule engine API surface, meant to be wired into sensor_fusion.py's
FastAPI app the same way the /actuators/* routes are.

Security posture matches the rest of the app rather than introducing a
new pattern:
  - GET /rules            - read-only, standard API key auth
  - GET /rules/fired       - read-only, standard API key auth
  - POST /rules/reload     - MUTATING (changes what logic runs against
                             live sensors/actuators) - requires admin
                             scope ("*") AND a valid MFA code if the
                             calling key has one configured, exactly
                             like /actuators/panic. Every reload is
                             logged at WARNING with the operator name.

  - POST /ics-ids/alert    - Lets a real protocol-aware ICS/OT
                             intrusion detection product (Claroty,
                             Dragos, Nozomi, etc.) push its findings
                             into this system's existing AlertManager
                             instead of that tool's alerts living in a
                             separate console nobody watches. This
                             does NOT replace such a product - see
                             TelemetryAnomalyMonitor's docstring in
                             sensor_fusion.py for why - it's a bridge,
                             not a substitute. Requires a scoped,
                             non-admin API key issued specifically to
                             the ICS-IDS integration.
"""
import logging
from fastapi import Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("sensor_fusion")


class ICSIDSAlert(BaseModel):
    source_product: str
    severity: str
    summary: str
    affected_asset: str = None
    protocol: str = None


def register_rule_routes(app, rule_engine_holder: dict, authenticate, verify_mfa, alert_channels_holder: dict):
    @app.get("/rules")
    def list_rules(x_api_key: str = Header(default="")):
        record = authenticate(x_api_key)
        if "*" not in record["scopes"]:
            raise HTTPException(status_code=403, detail="Only admin-scoped keys can view rules")
        engine = rule_engine_holder.get("engine")
        if engine is None:
            return {"rules": []}
        return {
            "rules": [
                {"id": r.id, "description": r.description, "enabled": r.enabled,
                 "allow_auto_command": r.allow_auto_command, "cooldown_seconds": r.cooldown_seconds}
                for r in engine.rules
            ]
        }

    @app.get("/rules/fired")
    def list_fired(x_api_key: str = Header(default=""), limit: int = 100):
        record = authenticate(x_api_key)
        if "*" not in record["scopes"]:
            raise HTTPException(status_code=403, detail="Only admin-scoped keys can view rule trigger history")
        engine = rule_engine_holder.get("engine")
        if engine is None:
            return []
        return engine.fired_log[-limit:]

    @app.post("/rules/reload")
    def reload_rules(x_api_key: str = Header(default=""), x_mfa_code: str = Header(default="")):
        record = authenticate(x_api_key)
        if "*" not in record["scopes"]:
            raise HTTPException(status_code=403, detail="Only a full-access key can reload rules")
        if not verify_mfa(record, x_mfa_code):
            raise HTTPException(status_code=401, detail="Valid MFA code required to reload rules")
        engine = rule_engine_holder.get("engine")
        if engine is None:
            raise HTTPException(status_code=503, detail="Rule engine not initialized on this node")
        engine.reload()
        logger.warning(f"Rules reloaded via API by operator='{record['name']}'")
        return {"reloaded": True, "rule_count": len(engine.rules)}

    @app.post("/ics-ids/alert")
    def ics_ids_alert(body: ICSIDSAlert, x_api_key: str = Header(default="")):
        record = authenticate(x_api_key)
        if not _scope_allows_ics(record["scopes"]):
            raise HTTPException(status_code=403, detail="Your API key isn't scoped for ICS-IDS integration")
        message = (f"[ICS-IDS:{body.source_product}] severity={body.severity} "
                   f"asset={body.affected_asset} protocol={body.protocol} - {body.summary}")
        for channel in alert_channels_holder.get("channels", []):
            channel.send(message)
        logger.warning(f"ICS-IDS ALERT relayed from '{body.source_product}': {message}")
        return {"relayed": True}


def _scope_allows_ics(scopes):
    return "*" in scopes or "ics_ids:*" in scopes or "ics_ids:alert" in scopes
