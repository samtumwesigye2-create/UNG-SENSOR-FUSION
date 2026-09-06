"""Replay / simulation mode for historical Sensor Fusion readings."""
import argparse, json, sqlite3, time
from datetime import datetime, timezone
from sensor_fusion import Reading, EventBus, WorldState, FusionEngine, KalmanStrategy
from rule_engine import RuleEngine

def _parse_time(s:str)->float:
    value=datetime.fromisoformat(s)
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    return value.timestamp()

def load_readings(db_path:str,since:float=None,until:float=None):
    conn=sqlite3.connect(db_path); clauses=[]; params=[]
    if since is not None: clauses.append("timestamp >= ?"); params.append(since)
    if until is not None: clauses.append("timestamp <= ?"); params.append(until)
    where=f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows=conn.execute(f"SELECT timestamp, sensor_id, data_type, value, confidence FROM readings {where} ORDER BY timestamp ASC",params).fetchall(); conn.close()
    return [Reading(sensor_id=r[1],data_type=r[2],value=json.loads(r[3]),confidence=r[4],timestamp=r[0]) for r in rows]

class ReplayEngine:
    def __init__(self,history_db:str,rules_path:str,fusion_strategies:dict=None):
        self.history_db=history_db; self.bus=EventBus(); self.world=WorldState()
        self.engine=FusionEngine(self.bus,self.world,strategies=fusion_strategies or {"position":KalmanStrategy()})
        self.rule_engine=RuleEngine(self.world,rules_path,alert_channels=[],command_center=None,dry_run=True)
    def run(self,since:float=None,until:float=None,speed:float=0.0):
        readings=load_readings(self.history_db,since,until)
        if not readings: return {"readings_replayed":0,"rule_triggers":[]}
        base_ts=readings[0].timestamp; base_wall=time.time()
        for reading in readings:
            if speed>0:
                target_wall=base_wall+(reading.timestamp-base_ts)/speed; delay=target_wall-time.time()
                if delay>0: time.sleep(delay)
            self.bus.publish(reading)
        return {"readings_replayed":len(readings),"time_range":{"since":readings[0].timestamp,"until":readings[-1].timestamp},"rule_triggers":self.rule_engine.fired_log}

def main():
    p=argparse.ArgumentParser(); p.add_argument("history_db"); p.add_argument("rules_path"); p.add_argument("--since"); p.add_argument("--until"); p.add_argument("--speed",type=float,default=0.0); args=p.parse_args()
    report=ReplayEngine(args.history_db,args.rules_path).run(_parse_time(args.since) if args.since else None,_parse_time(args.until) if args.until else None,args.speed)
    print(f"Replayed {report['readings_replayed']} reading(s)")
    print(f"Rule triggers: {len(report['rule_triggers'])}")

if __name__=="__main__": main()
