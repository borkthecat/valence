"""Create blind Label Studio task files for PII and human ranking review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import build_pii_tasks, build_pii_tasks_from_label_studio, build_ranking_tasks, load_jsonl, write_json


def _write_blind_copies(tasks: list[dict], output: Path, name: str) -> None:
    for reviewer in ("reviewer_a", "reviewer_b"):
        copied = []
        for task in tasks:
            copy = {**task, "meta": {**task.get("meta", {}), "reviewer_assignment": reviewer}}
            copied.append(copy)
        write_json(output / f"{name}-{reviewer}.json", copied)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human-only review pack without ground-truth leakage")
    parser.add_argument("--pii-source", type=Path)
    parser.add_argument("--pii-predictions", type=Path)
    parser.add_argument("--pii-label-studio-tasks", type=Path)
    parser.add_argument("--ranking-pairs", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("review-pack"))
    parser.add_argument("--pii-limit", type=int, default=500)
    parser.add_argument("--pii-calibration-count", type=int, default=30)
    parser.add_argument("--include-high-confidence-pii", action="store_true")
    parser.add_argument("--ranking-calibration-jobs", type=int, default=30)
    parser.add_argument("--allow-ranking-smoke", action="store_true")
    args = parser.parse_args()
    if not args.pii_source and not args.pii_label_studio_tasks and not args.ranking_pairs:
        parser.error("provide PII inputs, ranking pairs, or both")
    if bool(args.pii_source) != bool(args.pii_predictions):
        parser.error("--pii-source and --pii-predictions must be provided together")
    if args.pii_label_studio_tasks and args.pii_source:
        parser.error("use either --pii-label-studio-tasks or --pii-source/--pii-predictions")
    if args.pii_source:
        tasks = build_pii_tasks(
            load_jsonl(args.pii_source), load_jsonl(args.pii_predictions),
            limit=args.pii_limit, calibration_count=args.pii_calibration_count,
            uncertain_only=not args.include_high_confidence_pii,
        )
        _write_blind_copies(tasks, args.output_dir, "pii-tasks")
    if args.pii_label_studio_tasks:
        source_tasks = json.loads(args.pii_label_studio_tasks.read_text(encoding="utf-8"))
        if not isinstance(source_tasks, list):
            raise ValueError("--pii-label-studio-tasks must contain a JSON list")
        tasks = build_pii_tasks_from_label_studio(
            source_tasks, limit=args.pii_limit, calibration_count=args.pii_calibration_count,
        )
        _write_blind_copies(tasks, args.output_dir, "pii-tasks")
    if args.ranking_pairs:
        tasks = build_ranking_tasks(
            load_jsonl(args.ranking_pairs), calibration_jobs=args.ranking_calibration_jobs,
            strict_pilot=not args.allow_ranking_smoke,
        )
        _write_blind_copies(tasks, args.output_dir, "ranking-tasks")
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
