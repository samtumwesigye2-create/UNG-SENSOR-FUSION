"""Subscriber-side exactly-once-effect guard for at-least-once delivery."""
from __future__ import annotations
import logging
logger = logging.getLogger("sensor_fusion")
class DeduplicatingSubscriber:
    def __init__(self, subscriber_name, callback, dedup_store):
        self.subscriber_name, self.callback, self.dedup_store = subscriber_name, callback, dedup_store
    def __call__(self, event):
        mid, sid, seq = event["message_id"], event.get("sensor_id"), event.get("sequence")
        if self.dedup_store.seen_before(self.subscriber_name, sid, mid, seq):
            logger.debug("Duplicate ignored subscriber=%s message_id=%s", self.subscriber_name, mid)
            return False
        self.callback(event)
        self.dedup_store.mark_processed(self.subscriber_name, sid, mid, seq)
        return True
