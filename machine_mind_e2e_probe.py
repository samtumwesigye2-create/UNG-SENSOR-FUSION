from nexus_client import publish

result = publish(
    "analytics.observation" if "hepha" == "nova" else "perception.observation",
    {
        "subject": "machine-mind-hepha-acceptance",
        "status": "acceptance-test",
        "confidence": 0.99,
    },
    correlation_id="machine-mind-hepha-acceptance",
)
print("MACHINE_MIND_HEPHA_E2E", result)
if not result.get("sent"):
    raise SystemExit(1)
