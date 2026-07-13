"""Durable local-mode shadow run store; advisory records never alter outcomes."""
from __future__ import annotations
import json, sqlite3, uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field

class Model(BaseModel): model_config=ConfigDict(extra="forbid",frozen=True)
class ShadowInput(Model):
    tenant_id:str; source_event_id:str; case_id:str; job_digest:str; candidate_set_digest:str; input_schema_version:str; model_version:str; model_digest:str; policy_version:str; policy_digest:str; advisory_output:dict; advisory_output_digest:str; review_task_ids:tuple[str,...]=(); latency_ms:float=Field(ge=0); token_usage:int=Field(default=0,ge=0); provider_cost:float=Field(default=0,ge=0); retention_expires_at:datetime|None=None; trace_id:str
class ShadowStore:
 def __init__(self,path:str|Path):self.path=str(path);self.migrate()
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
  try:yield c;c.commit()
  except: c.rollback();raise
  finally:c.close()
 def migrate(self):
  with self.db() as c:c.execute("CREATE TABLE IF NOT EXISTS shadow_runs(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,outcome TEXT,comparison TEXT,parent_id TEXT,version INTEGER NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,idem TEXT NOT NULL,UNIQUE(tenant,idem))");c.execute("CREATE TABLE IF NOT EXISTS shadow_events(id INTEGER PRIMARY KEY,run_id TEXT,tenant TEXT,action TEXT,detail TEXT,created TEXT)")
 def submit(self,item:ShadowInput,key:str):
  now=datetime.now(UTC).isoformat()
  with self.db() as c:
   r=c.execute("SELECT * FROM shadow_runs WHERE tenant=? AND idem=?",(item.tenant_id,key)).fetchone()
   if r:return self.row(r)
   i=str(uuid.uuid4());c.execute("INSERT INTO shadow_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",(i,item.tenant_id,item.model_dump_json(),"completed",None,None,None,1,now,now,key));self.event(c,i,item.tenant_id,"submitted",{});return self.row(c.execute("SELECT * FROM shadow_runs WHERE id=?",(i,)).fetchone())
 def get(self,t,i):
  with self.db() as c:
   r=c.execute("SELECT * FROM shadow_runs WHERE id=? AND tenant=?",(i,t)).fetchone()
   if not r:raise KeyError(i)
   return self.row(r)
 def list(self,t):
  with self.db() as c:return [self.row(r) for r in c.execute("SELECT * FROM shadow_runs WHERE tenant=? ORDER BY created DESC",(t,))]
 def outcome(self,t,i,outcome,version):return self.update(t,i,"outcome_pending",version,"outcome",outcome,{"completed","review_pending","outcome_pending"})
 def compare(self,t,i,comparison,version):return self.update(t,i,"compared",version,"comparison",comparison,{"outcome_pending"})
 def replay(self,t,i,key):
  base=self.get(t,i); payload=ShadowInput.model_validate(json.loads(base["payload"])); replay=self.submit(payload,key)
  with self.db() as c:c.execute("UPDATE shadow_runs SET parent_id=? WHERE id=?",(i,replay["shadow_run_id"]));self.event(c,replay["shadow_run_id"],t,"replayed",{"parent":i})
  return self.get(t,replay["shadow_run_id"])
 def expire(self,t,i,version):return self.update(t,i,"expired",version,"outcome",None,{"completed","review_pending","outcome_pending","compared","failed"})
 def delete(self,t,i,version):return self.update(t,i,"deleted",version,"outcome",None,{"expired"})
 def update(self,t,i,status,version,column,value,allowed):
  with self.db() as c:
   r=c.execute("SELECT * FROM shadow_runs WHERE id=? AND tenant=?",(i,t)).fetchone()
   if not r:raise KeyError(i)
   if r["version"]!=version:raise ValueError("version conflict")
   if r["status"] not in allowed:raise ValueError("invalid state transition")
   c.execute(f"UPDATE shadow_runs SET status=?,{column}=?,version=?,updated=? WHERE id=?",(status,json.dumps(value) if value is not None else None,version+1,datetime.now(UTC).isoformat(),i));self.event(c,i,t,status,{column:value});return self.row(c.execute("SELECT * FROM shadow_runs WHERE id=?",(i,)).fetchone())
 def event(self,c,i,t,a,d):c.execute("INSERT INTO shadow_events(run_id,tenant,action,detail,created) VALUES(?,?,?,?,?)",(i,t,a,json.dumps(d),datetime.now(UTC).isoformat()))
 def row(self,r):return {"shadow_run_id":r["id"],"tenant_id":r["tenant"],"payload":r["payload"],"status":r["status"],"version":r["version"],"parent_id":r["parent_id"]}
 def events(self,t,i):
  with self.db() as c:return [dict(row) for row in c.execute("SELECT action,detail,created FROM shadow_events WHERE tenant=? AND run_id=? ORDER BY id",(t,i))]
 def export_minimized(self,t):
  """Export only immutable digests and policy outcomes; no candidate text is stored here."""
  return [{key:value for key,value in self.row(row).items() if key not in {"payload"}} | {"digests": {key: json.loads(row["payload"])[key] for key in ("job_digest","candidate_set_digest","advisory_output_digest")}} for row in self._rows(t)]
 def _rows(self,t):
  with self.db() as c:return c.execute("SELECT * FROM shadow_runs WHERE tenant=? AND status!='deleted' ORDER BY created",(t,)).fetchall()
 def report(self,t):
  rows=self._rows(t); total=len(rows)
  return {"total_cases":total,"status_counts":{status:sum(row["status"]==status for row in rows) for status in ("completed","review_pending","outcome_pending","compared","failed","expired")},"review_precision":"unmeasured","review_recall":"unmeasured","latency_p50":"unmeasured" if not rows else sorted(json.loads(row["payload"])["latency_ms"] for row in rows)[(total-1)//2]}
