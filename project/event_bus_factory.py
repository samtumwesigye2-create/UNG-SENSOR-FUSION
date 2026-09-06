"""Factory for selecting the event-bus backend from configuration."""
from __future__ import annotations
from event_bus_backend import InProcessBackend, RedisStreamsBackend

def create_event_bus_backend(config: dict):
    backend=config.get("event_bus_backend","in_process")
    if backend=="in_process": return InProcessBackend()
    if backend=="redis_streams":
        redis_cfg=config.get("redis_bus",{})
        return RedisStreamsBackend(url=redis_cfg.get("url","redis://localhost:6379/0"),stream=redis_cfg.get("stream","sensor_fusion.events"),consumer_name=redis_cfg.get("consumer_name","sensor-fusion"),block_ms=redis_cfg.get("block_ms",1000))
    raise ValueError(f"Unknown event_bus_backend: {backend}")
