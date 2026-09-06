import os, tempfile
from event_bus_backend import InProcessBackend
from subscriber_dedup import SubscriberDedupStore
from deduplicating_subscriber import DeduplicatingSubscriber

def test_success_then_duplicate_is_suppressed():
    with tempfile.TemporaryDirectory() as d:
        store=SubscriberDedupStore(os.path.join(d,"d.sqlite")); seen=[]
        sub=DeduplicatingSubscriber("history",seen.append,store)
        e={"message_id":"m1","sensor_id":"s1","sequence":1,"data_type":"x","value":1}
        assert sub(e) is True and sub(e) is False and len(seen)==1
        store.close()

def test_failed_callback_remains_retryable():
    with tempfile.TemporaryDirectory() as d:
        store=SubscriberDedupStore(os.path.join(d,"d.sqlite")); attempts=[]
        def flaky(e):
            attempts.append(e["message_id"])
            if len(attempts)==1: raise RuntimeError("temporary failure")
        sub=DeduplicatingSubscriber("history",flaky,store)
        e={"message_id":"m2","sensor_id":"s1","sequence":2,"data_type":"x","value":2}
        try: sub(e)
        except RuntimeError: pass
        assert sub(e) is True and sub(e) is False and attempts==["m2","m2"]
        store.close()

def test_older_sequence_is_suppressed():
    with tempfile.TemporaryDirectory() as d:
        store=SubscriberDedupStore(os.path.join(d,"d.sqlite")); seen=[]
        sub=DeduplicatingSubscriber("history",seen.append,store)
        for mid,seq in [("a",10),("b",9),("c",11)]:
            sub({"message_id":mid,"sensor_id":"s1","sequence":seq,"data_type":"x","value":seq})
        assert [x["message_id"] for x in seen]==["a","c"]
        store.close()

def test_backend_adapter():
    with tempfile.TemporaryDirectory() as d:
        store=SubscriberDedupStore(os.path.join(d,"d.sqlite")); seen=[]
        bus=InProcessBackend(); bus.subscribe(DeduplicatingSubscriber("history",seen.append,store))
        bus.publish("x",1,sensor_id="s1",sequence=1,message_id="m1")
        bus.publish("x",1,sensor_id="s1",sequence=1,message_id="m1")
        assert len(seen)==1
        store.close()
