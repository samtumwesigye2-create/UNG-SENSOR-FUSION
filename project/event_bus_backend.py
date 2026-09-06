"""
Event bus backend abstraction.

Stage 0/1 of the migration roadmap:
- InProcessBackend preserves the existing synchronous behavior.
- RedisStreamsBackend is an optional backend and is only selected when
  explicitly configured. Existing deployments remain unchanged by default.

Subscribers use the same publish/subscribe contract and never import Redis
directly.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger("sensor_fusion")

@dataclass(frozen=True)
class Event:
    message_id: str
    sensor_id: Optional[str]
    sequence: Optional[int]
    data_type: str
    value: Any
    def to_dict(self) -> dict:
        return {"message_id":self.message_id,"sensor_id":self.sensor_id,"sequence":self.sequence,"data_type":self.data_type,"value":self.value}

class EventBusBackend:
    def publish(self, data_type:str, value:Any, *, sensor_id:Optional[str]=None, sequence:Optional[int]=None, message_id:Optional[str]=None) -> str:
        raise NotImplementedError
    def subscribe(self, callback:Callable[[dict],None], *, group:str="default") -> None:
        raise NotImplementedError
    def close(self) -> None:
        pass

class InProcessBackend(EventBusBackend):
    def __init__(self):
        self._subscribers=[]; self._lock=threading.RLock()
    def subscribe(self, callback, *, group="default"):
        with self._lock: self._subscribers.append((group,callback))
    def publish(self, data_type, value, *, sensor_id=None, sequence=None, message_id=None):
        message_id=message_id or str(uuid.uuid4())
        event=Event(message_id,sensor_id,sequence,data_type,value).to_dict()
        with self._lock: subscribers=list(self._subscribers)
        for _,callback in subscribers: callback(event)
        return message_id

class RedisStreamsBackend(EventBusBackend):
    def __init__(self, url:str, stream:str="sensor_fusion.events", consumer_name:str="sensor-fusion", block_ms:int=1000):
        try: import redis
        except ImportError as exc: raise RuntimeError("RedisStreamsBackend requires the 'redis' Python package") from exc
        self._redis=redis.Redis.from_url(url,decode_responses=True)
        self.stream=stream; self.consumer_name=consumer_name; self.block_ms=block_ms
        self._closed=False; self._threads=[]; self._groups=set()
    def publish(self, data_type, value, *, sensor_id=None, sequence=None, message_id=None):
        message_id=message_id or str(uuid.uuid4())
        payload=Event(message_id,sensor_id,sequence,data_type,value).to_dict()
        self._redis.xadd(self.stream,{"event":json.dumps(payload,separators=(",",":"))})
        return message_id
    def subscribe(self, callback, *, group="default"):
        try:
            self._redis.xgroup_create(name=self.stream,groupname=group,id="0",mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc): raise
        self._groups.add(group)
        def consume():
            while not self._closed:
                try:
                    rows=self._redis.xreadgroup(group,self.consumer_name,{self.stream:">"},count=100,block=self.block_ms)
                    for _,messages in rows:
                        for message_id,fields in messages:
                            event=json.loads(fields["event"])
                            try:
                                callback(event); self._redis.xack(self.stream,group,message_id)
                            except Exception:
                                logger.exception("Event subscriber failed; message left pending group=%s message_id=%s",group,message_id)
                except Exception:
                    if not self._closed: logger.exception("Redis event consumer failure group=%s",group)
        thread=threading.Thread(target=consume,name=f"redis-events-{group}",daemon=True); thread.start(); self._threads.append(thread)
    def close(self):
        self._closed=True
        for thread in self._threads: thread.join(timeout=2)
        self._threads.clear()
