# Sensor Fusion — Rule Engine + Replay + Plugin Loading

This package advances the architecture roadmap through the first implementation slice:

1. Declarative `RuleEngine` with cooldowns and safe command gating.
2. Historical `ReplayEngine` running the rule engine in `dry_run` mode.
3. Filesystem-based `PluginLoader` for sensor/actuator registration.
4. API helpers for rule inspection/reload and ICS-IDS alert bridging.
5. Automated tests for the safety-critical rule and plugin behaviors.

## Safety boundaries

- Rules cannot auto-command by default.
- `allow_auto_command: true` is still insufficient for actuators that require human confirmation or are safety-critical.
- Replay never receives a live `CommandCenter` and always uses `dry_run=True`.
- Plugins execute arbitrary Python by design, so the `plugins/` directory must be deployment-controlled. There is intentionally no network upload endpoint.
- Plugin imports are isolated per file: a broken plugin is logged and skipped rather than crashing discovery.

## Event Streaming Backbone

The event pipeline exposes an `EventBusBackend` abstraction. `InProcessBackend` is authoritative by default. `RedisStreamsBackend` is available for explicitly configured staging/production use, while `ShadowEventBus` can mirror events to an experimental backend without allowing shadow failures to break the primary path.

`SubscriberDedupStore` tracks delivery independently per subscriber and sensor using message IDs plus monotonic sensor sequence numbers, preventing duplicate side effects during redelivery.

## Tests

Run:

```bash
python -m pytest -q
```
