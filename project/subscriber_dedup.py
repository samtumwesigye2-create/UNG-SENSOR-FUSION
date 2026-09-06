"""Subscriber-side delivery deduplication for the Redis Streams migration."""
from __future__ import annotations
import sqlite3, threading
from typing import Optional
class SubscriberDedupStore:
    def __init__(self,db_path:str,max_message_ids:int=10000):
        self.db_path=db_path; self.max_message_ids=max_message_ids; self._lock=threading.RLock()
        self._conn=sqlite3.connect(db_path,check_same_thread=False)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS subscriber_delivery(subscriber_name TEXT NOT NULL,sensor_id TEXT NOT NULL,last_sequence INTEGER,PRIMARY KEY(subscriber_name,sensor_id))""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS subscriber_message(subscriber_name TEXT NOT NULL,message_id TEXT NOT NULL,PRIMARY KEY(subscriber_name,message_id))""")
        self._conn.commit()
    def seen_before(self,subscriber_name:str,sensor_id:Optional[str],message_id:str,sequence:Optional[int]=None)->bool:
        sid=sensor_id or "<unknown>"
        with self._lock:
            row=self._conn.execute("SELECT 1 FROM subscriber_message WHERE subscriber_name=? AND message_id=?",(subscriber_name,message_id)).fetchone()
            if row: return True
            if sequence is not None:
                row=self._conn.execute("SELECT last_sequence FROM subscriber_delivery WHERE subscriber_name=? AND sensor_id=?",(subscriber_name,sid)).fetchone()
                if row and row[0] is not None and sequence<=row[0]: return True
        return False
    def mark_processed(self,subscriber_name:str,sensor_id:Optional[str],message_id:str,sequence:Optional[int]=None)->None:
        sid=sensor_id or "<unknown>"
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO subscriber_message(subscriber_name,message_id) VALUES(?,?)",(subscriber_name,message_id))
            if sequence is not None:
                self._conn.execute("INSERT INTO subscriber_delivery(subscriber_name,sensor_id,last_sequence) VALUES(?,?,?) ON CONFLICT(subscriber_name,sensor_id) DO UPDATE SET last_sequence=MAX(last_sequence,excluded.last_sequence)",(subscriber_name,sid,sequence))
            self._conn.execute("""DELETE FROM subscriber_message WHERE rowid IN (SELECT rowid FROM subscriber_message WHERE subscriber_name=? ORDER BY rowid DESC LIMIT -1 OFFSET ?)""",(subscriber_name,self.max_message_ids))
            self._conn.commit()
    def close(self):
        with self._lock: self._conn.close()
