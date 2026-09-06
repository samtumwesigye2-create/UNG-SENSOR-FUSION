import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rule_engine import RuleEngine, load_rules


class FakeWorld:
    def __init__(self):
        self.state = {}
        self.callbacks = []
    def on_update(self, callback):
        self.callbacks.append(callback)
    def snapshot(self):
        return dict(self.state)
    def update(self, data_type, value):
        self.state[data_type] = value
        for cb in self.callbacks:
            cb(data_type, value)


class FakeChannel:
    def __init__(self): self.messages = []
    def send(self, message): self.messages.append(message)


class FakeActuator:
    def __init__(self, requires_confirmation=False, safety_critical=False):
        self.requires_confirmation = requires_confirmation
        self.safety_critical = safety_critical


class FakeCommandCenter:
    def __init__(self, actuator):
        self.actuators = {"door": actuator}
        self.calls = []
    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"ok": True}


def write_rules(tmp_path, rules):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"rules": rules}))
    return str(path)


def test_alert_rule_triggers_and_cooldown(tmp_path):
    rules_path = write_rules(tmp_path, [{"id":"smoke","conditions":[{"field":"lobby:hazard_status","operator":"eq","value":"smoke"}],"actions":[{"kind":"alert","message":"SMOKE"}],"cooldown_seconds":300}])
    world = FakeWorld(); channel = FakeChannel(); engine = RuleEngine(world, rules_path, alert_channels=[channel])
    world.update("lobby:hazard_status", "smoke"); world.update("lobby:hazard_status", "smoke")
    assert len(engine.fired_log) == 1
    assert channel.messages == ["SMOKE"]


def test_command_defaults_to_disabled(tmp_path):
    rules_path = write_rules(tmp_path, [{"id":"lock","conditions":[{"field":"lobby:hazard_status","operator":"eq","value":"breach"}],"actions":[{"kind":"command","actuator_id":"door","command":"lock"}]}])
    world = FakeWorld(); cc = FakeCommandCenter(FakeActuator()); engine = RuleEngine(world, rules_path, command_center=cc)
    world.update("lobby:hazard_status", "breach")
    assert not cc.calls
    assert engine.fired_log[0]["results"][0]["dispatched"] is False


def test_confirmation_required_command_is_downgraded_to_alert(tmp_path):
    rules_path = write_rules(tmp_path, [{"id":"lock","conditions":[{"field":"lobby:hazard_status","operator":"eq","value":"breach"}],"actions":[{"kind":"command","actuator_id":"door","command":"lock"}],"allow_auto_command":True}])
    world = FakeWorld(); channel = FakeChannel(); cc = FakeCommandCenter(FakeActuator(requires_confirmation=True)); engine = RuleEngine(world, rules_path, alert_channels=[channel], command_center=cc)
    world.update("lobby:hazard_status", "breach")
    assert not cc.calls
    assert engine.fired_log[0]["results"][0]["downgraded_to_alert"] is True


def test_dry_run_never_executes_command(tmp_path):
    rules_path = write_rules(tmp_path, [{"id":"lock","conditions":[{"field":"lobby:hazard_status","operator":"eq","value":"breach"}],"actions":[{"kind":"command","actuator_id":"door","command":"lock"}],"allow_auto_command":True}])
    world = FakeWorld(); cc = FakeCommandCenter(FakeActuator()); engine = RuleEngine(world, rules_path, command_center=cc, dry_run=True)
    world.update("lobby:hazard_status", "breach")
    assert not cc.calls
    assert engine.fired_log[0]["results"][0]["reason"] == "dry_run"


def test_malformed_rule_is_skipped(tmp_path):
    rules_path = write_rules(tmp_path, [{"id":"bad","conditions":[{"field":"x"}],"actions":[]},{"id":"good","conditions":[{"field":"x","operator":"eq","value":1}],"actions":[{"kind":"alert","message":"ok"}]}])
    assert [r.id for r in load_rules(rules_path)] == ["good"]
