"""
Rule Engine
===========
Lets "if X and Y then alert/command Z" logic live in a JSON config file
(rules.json) instead of hardcoded Python classes like the
ZoneSecurityMonitor pattern. Subscribes to WorldState exactly the way
AlertManager does today - same interface, same bus, no changes to the
event pipeline required.

Safety model (this is the part that matters more than the JSON schema):

  - Rules are ALERT-ONLY by default. A rule can only issue a command to
    an actuator if it explicitly sets "allow_auto_command": true AND
    the target actuator is not safety_critical / requires_confirmation.
    Actuators that require human confirmation (per CommandCenter's
    existing request_confirmation flow) CANNOT be auto-confirmed by a
    rule - that would silently defeat the purpose of the confirmation
    step. If a matching rule targets such an actuator, it is executed
    as an ALERT ("this rule would have commanded X, but it requires
    human confirmation") instead of a command.

  - Every rule-triggered command goes through the exact same
    CommandCenter.execute() path a human command does - same audit
    table, same outcome tracking - but with operator="rule:<rule_id>"
    so the audit log always distinguishes automated from human action.

  - Cooldowns prevent a flapping condition from re-triggering (and
    re-alerting or re-commanding) every time WorldState updates.

  - A malformed rule is skipped and logged, not allowed to crash
    evaluation of every other rule.

  - Rules are reloadable at runtime (reload()), gated the same way
    /actuators/panic is gated in sensor_fusion.py: admin scope + MFA
    if the calling key has one configured. See rules_api.py.
"""
import json
import logging
import os
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("sensor_fusion")

_OPERATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and a > b,
    "gte": lambda a, b: a is not None and a >= b,
    "lt": lambda a, b: a is not None and a < b,
    "lte": lambda a, b: a is not None and a <= b,
    "in": lambda a, b: a in b,
    "contains": lambda a, b: isinstance(a, (list, str, dict)) and b in a,
    "exists": lambda a, b: (a is not None) == bool(b),
}


def _get_field(snapshot: dict, field_path: str):
    """
    field_path is a WorldState key, optionally with a dotted sub-path
    into a dict value, e.g. "lobby:hazard_status" or
    "lobby:camera_1.status".
    """
    if ":" not in field_path:
        return snapshot.get(field_path)
    key, _, rest = field_path.partition(".")
    value = snapshot.get(key)
    for part in rest.split(".") if rest else []:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


@dataclass
class RuleCondition:
    field: str
    operator: str
    value: Any = None

    def evaluate(self, snapshot: dict) -> bool:
        op = _OPERATORS.get(self.operator)
        if op is None:
            logger.error(f"Rule condition has unknown operator '{self.operator}' - treating as false")
            return False
        actual = _get_field(snapshot, self.field)
        try:
            return bool(op(actual, self.value))
        except TypeError:
            return False


@dataclass
class RuleAction:
    kind: str  # "alert" | "command"
    message: Optional[str] = None
    actuator_id: Optional[str] = None
    command: Optional[str] = None
    target: Optional[str] = None


@dataclass
class Rule:
    id: str
    description: str
    conditions: list  # list[RuleCondition], AND-ed together
    actions: list  # list[RuleAction]
    enabled: bool = True
    cooldown_seconds: float = 60.0
    allow_auto_command: bool = False
    watch_fields: list = field(default_factory=list)  # data_types that should trigger re-eval

    def matches(self, snapshot: dict) -> bool:
        return self.enabled and all(c.evaluate(snapshot) for c in self.conditions)


def _parse_rule(raw: dict) -> Rule:
    conditions = [RuleCondition(**c) for c in raw["conditions"]]
    actions = [RuleAction(**a) for a in raw["actions"]]
    watch_fields = raw.get("watch_fields") or [c.field.split(":")[0] for c in conditions]
    return Rule(
        id=raw["id"],
        description=raw.get("description", raw["id"]),
        conditions=conditions,
        actions=actions,
        enabled=raw.get("enabled", True),
        cooldown_seconds=raw.get("cooldown_seconds", 60.0),
        allow_auto_command=raw.get("allow_auto_command", False),
        watch_fields=watch_fields,
    )


def load_rules(path: str) -> list:
    if not os.path.exists(path):
        logger.warning(f"Rules file not found at {path} - rule engine starting with zero rules")
        return []
    with open(path) as f:
        raw_rules = json.load(f).get("rules", [])
    rules = []
    for raw in raw_rules:
        try:
            rules.append(_parse_rule(raw))
        except Exception as e:
            logger.error(f"Skipping malformed rule {raw.get('id', '<no id>')}: {e}")
    return rules


class RuleEngine:
    """
    dry_run=True (used by the replay engine) evaluates rules and
    records what WOULD have fired, without dispatching real alerts or
    commands - so new rules can be validated against historical data
    before they ever touch a live actuator.
    """

    def __init__(self, world_state, rules_path: str, alert_channels: list = None,
                 command_center=None, dry_run: bool = False):
        self.world_state = world_state
        self.rules_path = rules_path
        self.alert_channels = alert_channels or []
        self.command_center = command_center
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._last_triggered: dict = {}  # rule_id -> timestamp
        self.fired_log: list = []  # for dry_run / replay reporting
        self.rules = load_rules(rules_path)
        self._by_watch_field: dict = {}
        self._index_rules()
        # Always subscribe, dry_run or not - dry_run must only gate whether
        # _execute_action hits a real alert channel / CommandCenter (see
        # below), never whether the engine evaluates rules at all. Gating
        # the subscription itself would make replay mode evaluate nothing
        # and silently report "0 triggers" regardless of what the rules say.
        world_state.on_update(self._on_update)
        logger.info(f"RuleEngine loaded {len(self.rules)} rule(s) from {rules_path} (dry_run={dry_run})")

    def _index_rules(self):
        index = {}
        for rule in self.rules:
            for wf in rule.watch_fields:
                index.setdefault(wf, []).append(rule)
        self._by_watch_field = index

    def reload(self):
        with self._lock:
            self.rules = load_rules(self.rules_path)
            self._index_rules()
            self._last_triggered.clear()
        logger.warning(f"RuleEngine: reloaded {len(self.rules)} rule(s) from {self.rules_path}")

    def _on_update(self, data_type, value):
        zone = data_type.split(":")[0] if ":" in data_type else data_type
        candidates = self._by_watch_field.get(data_type, []) + self._by_watch_field.get(zone, [])
        if not candidates:
            return
        snapshot = self.world_state.snapshot()
        now = time.time()
        for rule in candidates:
            if not rule.matches(snapshot):
                continue
            last = self._last_triggered.get(rule.id, 0)
            if now - last < rule.cooldown_seconds:
                continue
            self._last_triggered[rule.id] = now
            self._fire(rule, snapshot, trigger_time=now)

    def _fire(self, rule: Rule, snapshot: dict, trigger_time: float):
        record = {"rule_id": rule.id, "description": rule.description, "timestamp": trigger_time, "results": []}
        for action in rule.actions:
            result = self._execute_action(rule, action, snapshot)
            record["results"].append(result)
        self.fired_log.append(record)
        logger.warning(f"RULE TRIGGERED id={rule.id} ({rule.description}) dry_run={self.dry_run}")

    def _execute_action(self, rule: Rule, action: RuleAction, snapshot: dict) -> dict:
        if action.kind == "alert":
            message = action.message or f"Rule '{rule.id}' triggered: {rule.description}"
            if self.dry_run:
                return {"kind": "alert", "message": message, "dispatched": False, "reason": "dry_run"}
            for channel in self.alert_channels:
                channel.send(message)
            return {"kind": "alert", "message": message, "dispatched": True}

        if action.kind == "command":
            return self._execute_command_action(rule, action)

        return {"kind": action.kind, "dispatched": False, "reason": "unknown action kind"}

    def _execute_command_action(self, rule: Rule, action: RuleAction) -> dict:
        if not rule.allow_auto_command:
            return {"kind": "command", "dispatched": False,
                    "reason": "rule does not have allow_auto_command: true"}
        if self.command_center is None:
            return {"kind": "command", "dispatched": False, "reason": "no command_center attached"}
        actuator = self.command_center.actuators.get(action.actuator_id)
        if actuator is None:
            return {"kind": "command", "dispatched": False,
                    "reason": f"unknown actuator {action.actuator_id}"}
        if actuator.requires_confirmation or actuator.safety_critical:
            # Never let a rule auto-confirm a command a human is supposed to gate.
            # Downgrade to an alert instead of silently skipping it.
            message = (f"Rule '{rule.id}' matched and WOULD command "
                       f"{action.actuator_id}:{action.command}, but that actuator requires "
                       f"human confirmation - alerting instead of auto-executing")
            if not self.dry_run:
                for channel in self.alert_channels:
                    channel.send(message)
            return {"kind": "command", "dispatched": False,
                    "reason": "actuator requires human confirmation", "downgraded_to_alert": True}
        if self.dry_run:
            return {"kind": "command", "dispatched": False, "reason": "dry_run",
                    "would_execute": {"actuator_id": action.actuator_id, "command": action.command}}
        try:
            result = self.command_center.execute(
                action.actuator_id, action.command,
                operator=f"rule:{rule.id}", reason=rule.description, target=action.target,
            )
            return {"kind": "command", "dispatched": True, "result": result}
        except Exception as e:
            return {"kind": "command", "dispatched": False, "reason": str(e)}
