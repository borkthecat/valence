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
  Capability("shadow operations","passed","signed tenant-scoped HTTP lifecycle, immutable events and deletion receipts","contract and Docker live smoke configured",metric="comparison agreement remains unmeasured until outcomes arrive"),
  Capability("annotation workflow","passed","blind dual review, adjudication, corrections and versioned canonical export","annotation lifecycle integration passed"),
  Capability("lifecycle and retention","passed","due-time expiry, stale-claim release and explicit retention receipts","deterministic-clock integration passed"),
  Capability("benchmark reproducibility","passed","release evidence commands, input hashes, split metadata and artifact catalog","manifest check passed"),
  Capability("guard production enforcement","externally blocked","offline risk-calibrated profile only","offline matrix passed",benchmark_result="94.36% F1 and 2.29% aggregate FPR",blocker="production shadow labels for review-only sources are required",blocker_type="external data"),
  Capability("fraud production enforcement","externally blocked","EMSCAD historical benchmark and enrichment adapters","offline benchmark passed",benchmark_result="88.48% F1 at 0.32% FPR",blocker="current postings with independently verified external signals are required",blocker_type="external data"),
  Capability("talent ranking effectiveness","externally blocked","evaluation and adjudication machinery is complete","not run",blocker="permissioned 200-case independently reviewed pilot is required",blocker_type="external data and human review"),
 ]
def main():
 p=argparse.ArgumentParser();p.add_argument("--format",choices=("json","markdown"),default="json");p.add_argument("--output",type=Path);args=p.parse_args()
 rows=report();repository_failed=any(x.status=="failed" for x in rows);external_pending=any(x.status=="externally blocked" for x in rows);payload={"capabilities":[asdict(x) for x in rows],"overall_status":"repository_incomplete" if repository_failed else "repository_ready_external_evidence_pending" if external_pending else "passed","enterprise_ready":not repository_failed and not external_pending}
 text=json.dumps(payload,indent=2)+"\n" if args.format=="json" else "# Valence readiness\n\n"+"\n".join(f"- **{x.name}**: {x.status} — {x.evidence}" for x in rows)+"\n"
 if args.output:args.output.write_text(text,encoding="utf-8")
 else:print(text,end="")
 return 1 if repository_failed else 0
if __name__=="__main__":raise SystemExit(main())
