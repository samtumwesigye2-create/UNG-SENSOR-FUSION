# UNG-HEPHA

**Heterogeneous Event Processing & Harmonization Architecture**

UNG-HEPHA is the UNG ecosystem's sensor-fusion and heterogeneous event-processing system. It ingests readings and events from multiple sources, verifies sensor identity/signatures, deduplicates repeated delivery, maintains a current fused world state, persists recent readings, and provides the rule-processing boundary used by downstream UNG systems.

## Compatibility

The existing repository, Railway project/service IDs, database schema names, API paths, security variables, and legacy `ung-sensor-fusion` service identifier are retained during the naming migration so current integrations do not break. `UNG-SENSOR-FUSION` is the legacy technical identity; `UNG-HEPHA` is the operational system name.

## Event Streaming Backbone — Stage 3

`DeduplicatingSubscriber` is the reusable subscriber boundary for at-least-once delivery. It suppresses previously processed message IDs/sequences and records delivery only after the wrapped callback succeeds. A failed callback remains retryable. The supplied repository does not contain the real `HistoryStore` implementation, so no fictitious end-to-end HistoryStore migration is claimed here.
