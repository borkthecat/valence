"""Emit a conservative, machine-readable local readiness report."""
from __future__ import annotations
import argparse, json
from dataclasses import asdict, dataclass
from pathlib import Path

VALID={"passed","failed","unmeasured","externally blocked","intentionally deferred","not applicable"}
@dataclass(frozen=True)
class Capability:
 name:str; status:str; evidence:str; test_result:str; benchmark_result:str="unmeasured"; metric:str="unmeasured"; confidence_interval:str="unmeasured"; blocker:str=""; blocker_type:str=""
 def __post_init__(self):
  if self.status not in VALID:raise ValueError("invalid readiness status")
def report():
 return [
  Capability("trusted review identity","passed","gateway signed internal envelope and service verification","contract smoke passed"),
  Capability("advisory review task persistence","passed","atomic tenant-scoped SQLite task store","contract smoke passed"),
  Capability("shadow operations","failed","local lifecycle store only","partial contract smoke passed",blocker="HTTP/RBAC shadow service and full lifecycle are incomplete",blocker_type="repository work"),
  Capability("annotation workflow","failed","blind local annotation store","partial contract smoke passed",blocker="reviewer application and versioned export are incomplete",blocker_type="repository work"),
  Capability("real-world effectiveness","unmeasured","no permissioned human-labelled production dataset","not run",blocker="human labels and approval required",blocker_type="external"),
 ]
def main():
 p=argparse.ArgumentParser();p.add_argument("--format",choices=("json","markdown"),default="json");p.add_argument("--output",type=Path);args=p.parse_args()
 rows=report();payload={"capabilities":[asdict(x) for x in rows],"overall_status":"failed" if any(x.status=="failed" for x in rows) else "passed"}
 text=json.dumps(payload,indent=2)+"\n" if args.format=="json" else "# Valence readiness\n\n"+"\n".join(f"- **{x.name}**: {x.status} — {x.evidence}" for x in rows)+"\n"
 if args.output:args.output.write_text(text,encoding="utf-8")
 else:print(text,end="")
 return 1 if payload["overall_status"]=="failed" else 0
if __name__=="__main__":raise SystemExit(main())
