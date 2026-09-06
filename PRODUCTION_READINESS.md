# Production readiness

Stage 3 is the authoritative subscriber/event-streaming extension. All included tests pass.
The archive still does not contain the original `sensor_fusion.py` core/HistoryStore, so this
bundle is not a standalone service by itself. Merge these modules into the core Sensor Fusion
repository before deployment. Use `config.production.template.json` as a secret-free baseline;
it defaults sensor signatures ON and command ingress OFF (`ingest_only_mode=true`).
