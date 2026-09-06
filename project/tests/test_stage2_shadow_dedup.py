import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from subscriber_dedup import SubscriberDedupStore
from event_bus_backend import InProcessBackend
from shadow_event_bus import ShadowEventBus


def test_duplicate_message_is_seen_before():
    with tempfile.TemporaryDirectory() as d:
        store = SubscriberDedupStore(os.path.join(d, "dedup.sqlite"))
        assert not store.seen_before("history", "s1", "m1", 1)
        store.mark_processed("history", "s1", "m1", 1)
        assert store.seen_before("history", "s1", "m1", 1)
        store.close()


def test_older_sequence_is_seen_before():
    with tempfile.TemporaryDirectory() as d:
        store = SubscriberDedupStore(os.path.join(d, "dedup.sqlite"))
        store.mark_processed("history", "s1", "m10", 10)
        assert store.seen_before("history", "s1", "m9", 9)
        assert not store.seen_before("history", "s1", "m11", 11)
        store.close()


def test_subscribers_have_independent_delivery_state():
    with tempfile.TemporaryDirectory() as d:
        store = SubscriberDedupStore(os.path.join(d, "dedup.sqlite"))
        store.mark_processed("history", "s1", "m1", 1)
        assert store.seen_before("history", "s1", "m1", 1)
        assert not store.seen_before("alerts", "s1", "m1", 1)
        store.close()


def test_shadow_failure_does_not_break_primary():
    class Broken:
        def publish(self, *a, **kw):
            raise RuntimeError("redis unavailable")
        def close(self):
            pass
    primary = InProcessBackend()
    seen = []
    primary.subscribe(seen.append)
    bus = ShadowEventBus(primary, Broken())
    mid = bus.publish("co2_ppm", 420, sensor_id="s1", sequence=1)
    assert seen[0]["message_id"] == mid
