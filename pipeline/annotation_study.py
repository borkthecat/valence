"""Persisted blind annotation/adjudication workflow; no system output is stored."""
from __future__ import annotations
import json,sqlite3
from contextlib import contextmanager
from datetime import UTC,datetime
from pathlib import Path

MATERIAL={"hard_eligibility","human_review_required","evidence_sufficiency","fraud_or_inconsistency_risk","graded_relevance"}
class StudyStore:
 def __init__(self,path:str|Path):self.path=str(path);self.migrate()
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row
  try:yield c;c.commit()
  except:c.rollback();raise
  finally:c.close()
 def migrate(self):
  with self.db() as c:
   c.execute("CREATE TABLE IF NOT EXISTS study_cases(id TEXT PRIMARY KEY,tenant TEXT,state TEXT NOT NULL,record TEXT NOT NULL,version INTEGER NOT NULL)");c.execute("CREATE TABLE IF NOT EXISTS assignments(case_id TEXT,reviewer TEXT,PRIMARY KEY(case_id,reviewer))");c.execute("CREATE TABLE IF NOT EXISTS annotations(case_id TEXT,reviewer TEXT,payload TEXT,final INTEGER,PRIMARY KEY(case_id,reviewer))");c.execute("CREATE TABLE IF NOT EXISTS resolutions(case_id TEXT PRIMARY KEY,adjudicator TEXT,payload TEXT,reason TEXT,created TEXT)")
 def add_case(self,tenant,case_id,record,reviewers):
  with self.db() as c:c.execute("INSERT INTO study_cases VALUES(?,?,?,?,1)",(case_id,tenant,"calibration",json.dumps(record)));[c.execute("INSERT INTO assignments VALUES(?,?)",(case_id,r)) for r in reviewers]
 def queue(self,tenant,reviewer):
  with self.db() as c:return [r["id"] for r in c.execute("SELECT s.id FROM study_cases s JOIN assignments a ON s.id=a.case_id LEFT JOIN annotations n ON n.case_id=s.id AND n.reviewer=a.reviewer WHERE s.tenant=? AND a.reviewer=? AND n.final IS NULL AND s.state IN ('calibration','annotation')",(tenant,reviewer))]
 def case(self,tenant,case_id,actor,adjudicator=False):
  with self.db() as c:
   r=c.execute("SELECT * FROM study_cases WHERE id=? AND tenant=?",(case_id,tenant)).fetchone()
   if not r:raise KeyError(case_id)
   if not adjudicator and not c.execute("SELECT 1 FROM assignments WHERE case_id=? AND reviewer=?",(case_id,actor)).fetchone():raise PermissionError()
   record=json.loads(r["record"]);return {"case_id":case_id,"state":r["state"],"job":record.get("job"),"candidates":record.get("candidates")} # deliberately excludes outputs/other labels
 def save(self,tenant,case_id,reviewer,payload,final=False):
  case=self.case(tenant,case_id,reviewer)
  if case["state"]=="frozen":raise ValueError("frozen datasets cannot be edited")
  with self.db() as c:
   current=c.execute("SELECT final FROM annotations WHERE case_id=? AND reviewer=?",(case_id,reviewer)).fetchone()
   if current and current["final"]:raise ValueError("submitted annotations are immutable")
   c.execute("INSERT INTO annotations VALUES(?,?,?,?) ON CONFLICT(case_id,reviewer) DO UPDATE SET payload=excluded.payload,final=excluded.final",(case_id,reviewer,json.dumps(payload),int(final)))
 def disagreements(self,tenant,case_id):
  with self.db() as c:
   rows=c.execute("SELECT payload FROM annotations WHERE case_id=? AND final=1",(case_id,)).fetchall()
   if len(rows)<2:return {}
   a,b=[json.loads(r["payload"]) for r in rows[:2]];return {k:(a.get(k),b.get(k)) for k in MATERIAL if a.get(k)!=b.get(k) and (k!="graded_relevance" or abs(a.get(k,0)-b.get(k,0))>1)}
 def adjudicate(self,tenant,case_id,actor,resolution,reason):
  if not self.disagreements(tenant,case_id):raise ValueError("no material disagreement")
  if not reason:raise ValueError("adjudication reason is required")
  with self.db() as c:
   if c.execute("SELECT 1 FROM resolutions WHERE case_id=?",(case_id,)).fetchone():raise ValueError("resolution is immutable; create a new dataset version")
   c.execute("INSERT INTO resolutions VALUES(?,?,?,?,?)",(case_id,actor,json.dumps(resolution),reason,datetime.now(UTC).isoformat()));c.execute("UPDATE study_cases SET state='adjudication',version=version+1 WHERE id=? AND tenant=?",(case_id,tenant))
 def freeze(self,tenant,case_id):
  with self.db() as c:c.execute("UPDATE study_cases SET state='frozen',version=version+1 WHERE id=? AND tenant=?",(case_id,tenant))
