from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    result = {}
    for row in rows:
        task_id = str(row.get("task_id", ""))
        score = row.get("score")
        if not task_id or not isinstance(score, int) or not 0 <= score <= 5:
            raise ValueError(f"invalid judge response in {path}")
        if task_id in result:
            raise ValueError(f"duplicate task_id {task_id} in {path}")
        result[task_id] = row
    return result


def adjudicate(
    tasks: list[dict[str, Any]],
    reviewer_a: dict[str, dict[str, Any]],
    reviewer_b: dict[str, dict[str, Any]],
    adjudicator: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels = []
    unresolved = disagreements = 0
    for task in tasks:
        task_id = str(task["task_id"])
        if task_id not in reviewer_a or task_id not in reviewer_b:
            raise ValueError(f"missing dual review for {task_id}")
        score_a = int(reviewer_a[task_id]["score"])
        score_b = int(reviewer_b[task_id]["score"])
        disagreement = abs(score_a - score_b)
        disagreements += int(disagreement > 1)
        resolution = "dual_agreement"
        if disagreement <= 1:
            resolved_score = round((score_a + score_b) / 2)
        elif adjudicator is not None and task_id in adjudicator:
            resolved_score = int(adjudicator[task_id]["score"])
            resolution = "model_adjudicated"
        else:
            resolved_score = None
            resolution = "unresolved"
            unresolved += 1
        labels.append({
            "task_id": task_id,
            "job_id": task["job_id"],
            "candidate_id": task["candidate_id"],
            "reviewer_scores": [score_a, score_b],
            "resolved_score": resolved_score,
            "resolution": resolution,
            "evidence_level": "silver_pseudo_label",
            "release_gate_eligible": False,
        })
    summary = {
        "tasks": len(tasks),
        "materialDisagreements": disagreements,
        "unresolved": unresolved,
        "agreementRateWithinOne": 1 - disagreements / len(tasks) if tasks else 0.0,
        "evidenceLevel": "silver_pseudo_label",
        "releaseGateEligible": False,
    }
    return labels, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge two independent ranking judges and optional adjudication")
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--reviewer-a", type=Path, required=True)
    parser.add_argument("--reviewer-b", type=Path, required=True)
    parser.add_argument("--adjudicator", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    tasks = [json.loads(line) for line in args.tasks.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    labels, summary = adjudicate(
        tasks, _load(args.reviewer_a), _load(args.reviewer_b),
        None if args.adjudicator is None else _load(args.adjudicator),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in labels), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["unresolved"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
