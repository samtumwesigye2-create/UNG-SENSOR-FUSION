# Sensor Fusion System — Architecture Roadmap

## Current architecture
Sensors publish readings into an event bus. Fusion logic normalizes and combines readings, updates world state, records history, evaluates rules, emits alerts, and can relay signed events to downstream UNG systems. Commands are kept on a separate authenticated path and ingest-only nodes can disable command execution entirely.

## Rule Engine + Replay
Rules are declarative configuration rather than hardcoded control logic. Conditions evaluate against world state and actions may alert or request commands. Automatic commands remain disabled by default; safety-critical or confirmation-required actuators cannot be bypassed. Cooldowns prevent flapping conditions from repeatedly firing actions.

Replay runs historical readings through a throwaway processing path with `dry_run=True`, producing a report of actions that would have occurred without touching live actuators.

## Plugin Loading
Sensor and actuator adapters are discovered from deployment-controlled Python modules. Each loaded plugin is hashed and logged. A broken plugin is isolated and skipped instead of crashing the fusion node. Runtime plugin upload is intentionally unsupported.

## Event Streaming Backbone
`EventBusBackend` separates producers/consumers from transport. `InProcessBackend` remains the safe default. Redis Streams can be enabled explicitly. `ShadowEventBus` mirrors traffic to an experimental backend while preserving the authoritative path if the shadow backend fails.

`SubscriberDedupStore` maintains independent subscriber delivery state and rejects duplicate message IDs or older sensor sequence numbers before side effects occur.

## Security boundaries
- Sensor identity and signatures are verified at ingest when required.
- Administrative API access uses service/API keys and production secrets come from environment-backed secret stores.
- Rules never bypass command authorization, actuator confirmation, or audit controls.
- Plugins are deployment-controlled code and must not be writable by untrusted users.
- Downstream integrations should use JANUS for identity/authorization and PULSAR for relay where configured.
- Production should use PostgreSQL for durable history and Redis Streams only after shadow validation.

## Production sequence
1. In-process authoritative event path.
2. Subscriber deduplication.
3. Shadow Redis event publication.
4. Compare ordering, loss, duplication, and latency.
5. Migrate non-critical subscribers first.
6. Preserve rollback to in-process operation.
