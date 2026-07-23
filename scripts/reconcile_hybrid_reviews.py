"""Reconcile two blind Label Studio exports and enforce calibration agreement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import choice, cohen_kappa, latest_annotation, pii_spans, write_json


def _key(task: dict[str, Any]) -> tuple[str, str, str]:
    data = task.get("data", {})
    meta = task.get("meta", {})
    return str(meta.get("review_kind")), str(data.get("record_id") or data.get("job_id")), str(data.get("candidate_id") or "")


def _load(path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError(f"{path} must be a Label Studio JSON task array")
    return {_key(task): task for task in tasks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile blind human review exports")
    parser.add_argument("reviewer_a", type=Path)
    parser.add_argument("reviewer_b", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-kappa", type=float, default=0.80)
    parser.add_argument("--allow-low-agreement", action="store_true")
    args = parser.parse_args()
    left, right = _load(args.reviewer_a), _load(args.reviewer_b)
    common = sorted(set(left) & set(right))
    if not common:
        raise ValueError("no matching tasks in reviewer exports")
    calibration_left: list[str] = []
    calibration_right: list[str] = []
    consensus, adjudication = [], []
    for task_key in common:
        a, b = latest_annotation(left[task_key]), latest_annotation(right[task_key])
        if not a or not b:
            adjudication.append({"task": task_key, "reason": "missing_review"})
            continue
        task = left[task_key]
        stage = task.get("meta", {}).get("review_stage")
        if task_key[0] == "pii":
            a_spans, b_spans = pii_spans(a), pii_spans(b)
            if a_spans == b_spans:
                consensus.append({"task": task_key, "pii_spans": sorted(a_spans), "status": "consensus"})
            else:
                adjudication.append({"task": task_key, "reason": "pii_span_disagreement", "reviewer_a": sorted(a_spans), "reviewer_b": sorted(b_spans)})
        else:
            a_score, b_score = choice(a, "final_relevance"), choice(b, "final_relevance")
            if stage == "calibration" and a_score is not None and b_score is not None:
                calibration_left.append(a_score)
                calibration_right.append(b_score)
            if a_score == b_score and a_score is not None:
                consensus.append({"task": task_key, "final_relevance": a_score, "status": "consensus"})
            else:
                adjudication.append({"task": task_key, "reason": "ranking_disagreement", "reviewer_a": a_score, "reviewer_b": b_score})
    kappa = cohen_kappa(calibration_left, calibration_right) if calibration_left else None
    report = {"common_tasks": len(common), "consensus": len(consensus), "needs_adjudication": len(adjudication), "calibration_pairs": len(calibration_left), "cohen_kappa": kappa, "minimum_kappa": args.minimum_kappa}
    write_json(args.output_dir / "consensus.json", consensus)
    write_json(args.output_dir / "needs-adjudication.json", adjudication)
    write_json(args.output_dir / "summary.json", report)
    print(json.dumps(report, sort_keys=True))
    if kappa is not None and kappa < args.minimum_kappa and not args.allow_low_agreement:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
