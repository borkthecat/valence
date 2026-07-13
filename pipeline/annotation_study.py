"""Tenant-scoped, blind dual-review annotation study lifecycle."""
from __future__ import annotations
import hashlib,json,sqlite3,uuid
from contextlib import contextmanager
from datetime import UTC,datetime
from pathlib import Path

STATES={"calibration","active","adjudication","frozen","exported"}
MATERIAL={"hard_eligibility","human_review_required","evidence_sufficiency","fraud_or_inconsistency_risk"}
def _now():return datetime.now(UTC).isoformat()
def _canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def _digest(v):return "sha256:"+hashlib.sha256(_canon(v).encode()).hexdigest()
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
   c.execute("CREATE TABLE IF NOT EXISTS study_cases(id TEXT PRIMARY KEY,tenant TEXT NOT NULL,dataset_version TEXT NOT NULL,state TEXT NOT NULL,record TEXT NOT NULL,version INTEGER NOT NULL,excluded_reason TEXT,UNIQUE(tenant,dataset_version,id))")
   c.execute("CREATE TABLE IF NOT EXISTS assignments(case_id TEXT NOT NULL,reviewer TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(case_id,reviewer))")
   c.execute("CREATE TABLE IF NOT EXISTS annotations(case_id TEXT NOT NULL,reviewer TEXT NOT NULL,payload TEXT NOT NULL,final INTEGER NOT NULL,PRIMARY KEY(case_id,reviewer))")
   c.execute("CREATE TABLE IF NOT EXISTS resolutions(case_id TEXT PRIMARY KEY,adjudicator TEXT NOT NULL,payload TEXT NOT NULL,reason TEXT NOT NULL,label_version INTEGER NOT NULL,created TEXT NOT NULL)")
   c.execute("CREATE TABLE IF NOT EXISTS exclusions(tenant TEXT NOT NULL,case_id TEXT NOT NULL,reviewer TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(tenant,case_id,reviewer))")
 def create_calibration_batch(self,tenant,records,reviewers,dataset_version="v1",conflicts=()):
  if len(set(reviewers))<2:raise ValueError("blind dual review requires two reviewers")
  ids=[]
  for index,record in enumerate(records):
   case_id=str(record.get("case_id") or f"cal-{uuid.uuid4()}");self.add_case(tenant,case_id,record,reviewers,dataset_version,"calibration",conflicts);ids.append(case_id)
  return tuple(ids)
 def add_case(self,tenant,case_id,record,reviewers,dataset_version="v1",state="calibration",conflicts=()):
  if state not in {"calibration","active"}:raise ValueError("cases start calibration or active")
  eligible=[r for r in reviewers if r not in set(conflicts)]
  if len(eligible)<2:raise ValueError("conflict exclusions leave fewer than two reviewers")
  with self.db() as c:
   c.execute("INSERT INTO study_cases VALUES(?,?,?,?,?,?,NULL)",(case_id,tenant,dataset_version,state,_canon(record),1))
   for reviewer in conflicts:c.execute("INSERT INTO exclusions VALUES(?,?,?,?)",(tenant,case_id,reviewer,"conflict_of_interest"))
   workloads={r:c.execute("SELECT count(*) FROM assignments a JOIN study_cases s ON s.id=a.case_id WHERE s.tenant=? AND a.reviewer=? AND a.role='reviewer'",(tenant,r)).fetchone()[0] for r in eligible}
   selected=sorted(eligible,key=lambda r:(workloads[r],r))[:2]
   for reviewer in selected:c.execute("INSERT INTO assignments VALUES(?,?,?)",(case_id,reviewer,"reviewer"))
 def activate(self,tenant,case_id):self._state(tenant,case_id,{"calibration"},"active")
 def _state(self,tenant,case_id,allowed,target):
  with self.db() as c:
   row=c.execute("SELECT state FROM study_cases WHERE id=? AND tenant=?",(case_id,tenant)).fetchone()
   if not row:raise KeyError(case_id)
   if row["state"] not in allowed:raise ValueError("invalid study state transition")
   c.execute("UPDATE study_cases SET state=?,version=version+1 WHERE id=? AND tenant=?",(target,case_id,tenant))
 def queue(self,tenant,reviewer):
  with self.db() as c:return [r["id"] for r in c.execute("SELECT s.id FROM study_cases s JOIN assignments a ON s.id=a.case_id LEFT JOIN annotations n ON n.case_id=s.id AND n.reviewer=a.reviewer WHERE s.tenant=? AND a.reviewer=? AND a.role='reviewer' AND n.final IS NULL AND s.state IN ('calibration','active') ORDER BY s.id",(tenant,reviewer))]
 def case(self,tenant,case_id,actor,adjudicator=False):
  with self.db() as c:
   row=c.execute("SELECT * FROM study_cases WHERE id=? AND tenant=?",(case_id,tenant)).fetchone()
   if not row:raise KeyError(case_id)
   if not adjudicator and not c.execute("SELECT 1 FROM assignments WHERE case_id=? AND reviewer=? AND role='reviewer'",(case_id,actor)).fetchone():raise PermissionError("not assigned")
   record=json.loads(row["record"]);return {"case_id":case_id,"dataset_version":row["dataset_version"],"state":row["state"],"job":record.get("job"),"candidates":record.get("candidates")}
 def save(self,tenant,case_id,reviewer,payload,final=False):
  case=self.case(tenant,case_id,reviewer)
  if case["state"] in {"frozen","exported","adjudication"}:raise ValueError("case is not editable")
  with self.db() as c:
   cur=c.execute("SELECT final FROM annotations WHERE case_id=? AND reviewer=?",(case_id,reviewer)).fetchone()
   if cur and cur["final"]:raise ValueError("submitted annotations are immutable")
   c.execute("INSERT INTO annotations VALUES(?,?,?,?) ON CONFLICT(case_id,reviewer) DO UPDATE SET payload=excluded.payload,final=excluded.final",(case_id,reviewer,_canon(payload),int(final)))
  if final:self._evaluate(tenant,case_id)
 def _labels(self,tenant,case_id):
  with self.db() as c:return [json.loads(r["payload"]) for r in c.execute("SELECT a.payload FROM annotations a JOIN study_cases s ON s.id=a.case_id WHERE s.tenant=? AND a.case_id=? AND a.final=1 ORDER BY a.reviewer",(tenant,case_id))]
 def disagreements(self,tenant,case_id,confidence_delta=.25):
  rows=self._labels(tenant,case_id)
  if len(rows)!=2:return {}
  a,b=rows;d={k:(a.get(k),b.get(k)) for k in MATERIAL if a.get(k)!=b.get(k)}
  if abs(a.get("graded_relevance",0)-b.get("graded_relevance",0))>1:d["graded_relevance"]=(a.get("graded_relevance"),b.get("graded_relevance"))
  if abs(float(a.get("confidence",0))-float(b.get("confidence",0)))>confidence_delta:d["confidence"]=(a.get("confidence"),b.get("confidence"))
  return d
 def _evaluate(self,tenant,case_id):
  labels=self._labels(tenant,case_id)
  if len(labels)!=2:return
  if self.disagreements(tenant,case_id):self._state(tenant,case_id,{"calibration","active"},"adjudication")
 def assign_adjudicator(self,tenant,case_id,adjudicator):
  if not self.disagreements(tenant,case_id):raise ValueError("adjudication requires material disagreement")
  with self.db() as c:c.execute("INSERT INTO assignments VALUES(?,?,?) ON CONFLICT(case_id,reviewer) DO UPDATE SET role='adjudicator'",(case_id,adjudicator,"adjudicator"))
 def adjudicate(self,tenant,case_id,actor,resolution,reason):
  if not reason or not self.disagreements(tenant,case_id):raise ValueError("material disagreement and reason required")
  with self.db() as c:
   if not c.execute("SELECT 1 FROM assignments WHERE case_id=? AND reviewer=? AND role='adjudicator'",(case_id,actor)).fetchone():raise PermissionError("adjudicator not assigned")
   if c.execute("SELECT 1 FROM resolutions WHERE case_id=?",(case_id,)).fetchone():raise ValueError("resolution is immutable")
   c.execute("INSERT INTO resolutions VALUES(?,?,?,?,?,?)",(case_id,actor,_canon(resolution),reason,1,_now()))
 def freeze(self,tenant,case_id):
  labels=self._labels(tenant,case_id);d=self.disagreements(tenant,case_id)
  if len(labels)!=2:raise ValueError("freeze requires two independent submissions")
  if not d and labels[0] != labels[1]:raise ValueError("non-material label differences must be reconciled before agreement")
  if d:
   with self.db() as c:
    if not c.execute("SELECT 1 FROM resolutions WHERE case_id=?",(case_id,)).fetchone():raise ValueError("material disagreement requires adjudication")
  self._state(tenant,case_id,{"calibration","active","adjudication"},"frozen")
 def correct(self,tenant,case_id,record,reviewers):
  with self.db() as c:
   old=c.execute("SELECT dataset_version,state FROM study_cases WHERE id=? AND tenant=?",(case_id,tenant)).fetchone()
   if not old or old["state"] not in {"frozen","exported"}:raise ValueError("corrections require frozen source")
  new_id=f"{case_id}-v{int(old['dataset_version'].lstrip('v') or 1)+1}";self.add_case(tenant,new_id,record,reviewers,f"v{int(old['dataset_version'].lstrip('v') or 1)+1}","calibration");return new_id
 def export(self,tenant,output:Path):
  with self.db() as c:rows=c.execute("SELECT * FROM study_cases WHERE tenant=? AND state='frozen' ORDER BY id",(tenant,)).fetchall()
  records=[];exclusions=[]
  for row in rows:
   labels=self._labels(tenant,row["id"]);d=self.disagreements(tenant,row["id"])
   with self.db() as c:res=c.execute("SELECT * FROM resolutions WHERE case_id=?",(row["id"],)).fetchone();exc=c.execute("SELECT reviewer,reason FROM exclusions WHERE tenant=? AND case_id=?",(tenant,row["id"])).fetchall()
   records.append({"case_id":row["id"],"dataset_version":row["dataset_version"],"record":json.loads(row["record"]),"independent_labels":labels,"adjudication_status":"adjudicated" if d else "agreed","resolved_labels":json.loads(res["payload"]) if res else labels[0]});exclusions += [{"case_id":row["id"],**dict(x)} for x in exc]
  output.mkdir(parents=True,exist_ok=True);jsonl="\n".join(_canon(x) for x in records)+("\n" if records else "");(output/"canonical.jsonl").write_text(jsonl,encoding="utf-8")
  manifest={"tenant":tenant,"records":len(records),"dataset_digest":_digest(records)};agreement={"agreed":sum(x["adjudication_status"]=="agreed" for x in records),"adjudicated":sum(x["adjudication_status"]=="adjudicated" for x in records)};audit={"all_frozen":True,"records":len(records)};benchmark={"dataset_digest":manifest["dataset_digest"],"declared_split":"pilot","primary_metrics":["review_agreement"],"exclusions":len(exclusions)}
  for name,value in {"dataset_manifest.json":manifest,"benchmark_manifest.json":benchmark,"agreement_report.json":agreement,"audit_report.json":audit,"exclusion_report.json":exclusions}.items():(output/name).write_text(json.dumps(value,sort_keys=True,indent=2)+"\n",encoding="utf-8")
  for row in rows:self._state(tenant,row["id"],{"frozen"},"exported")
  return manifest
