"""Shadow-mode fanout for migration validation."""
from __future__ import annotations
import logging
logger=logging.getLogger("sensor_fusion")
class ShadowEventBus:
    def __init__(self,primary,shadow): self.primary,self.shadow=primary,shadow
    def publish(self,data_type,value,*,sensor_id=None,sequence=None,message_id=None):
        if message_id is None:
            import uuid; message_id=str(uuid.uuid4())
        primary_id=self.primary.publish(data_type,value,sensor_id=sensor_id,sequence=sequence,message_id=message_id)
        try: self.shadow.publish(data_type,value,sensor_id=sensor_id,sequence=sequence,message_id=message_id)
        except Exception: logger.exception("SHADOW PUBLISH FAILED message_id=%s data_type=%s",message_id,data_type)
        return primary_id
    def subscribe(self,callback,*,group="default"): return self.primary.subscribe(callback,group=group)
    def close(self): self.primary.close(); self.shadow.close()
