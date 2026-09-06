import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from event_bus_backend import InProcessBackend
from event_bus_factory import create_event_bus_backend


def test_in_process_backend_preserves_order_and_message_metadata():
    bus = InProcessBackend()
    seen = []
    bus.subscribe(seen.append)
    first = bus.publish("temperature", 21.5, sensor_id="s1", sequence=1)
    second = bus.publish("temperature", 21.7, sensor_id="s1", sequence=2)
    assert first != second
    assert [x["sequence"] for x in seen] == [1, 2]
    assert [x["sensor_id"] for x in seen] == ["s1", "s1"]


def test_factory_defaults_to_in_process():
    assert isinstance(create_event_bus_backend({}), InProcessBackend)


def test_factory_rejects_unknown_backend():
    try:
        create_event_bus_backend({"event_bus_backend": "nope"})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown backend should fail explicitly")
