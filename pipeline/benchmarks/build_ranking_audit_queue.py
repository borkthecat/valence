from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {line_number} must be an object")
            rows.append(row)
    if not rows:
        raise ValueError("input is empty")
    return rows


def _score(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)


def _stable_id(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key, "")) for key in ("job_id", "candidate_id", "task_id"))


def _dedupe(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = []
    seen = set()
    for row in rows:
        stable_id = _stable_id(row)
        if stable_id in seen:
            continue
        selected.append(row)
        seen.add(stable_id)
        if len(selected) >= limit:
            break
    return selected


def audit_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    enriched = []
    for row in rows:
        ranker = _score(row, "ranker_score")
        judge = _score(row, "judge_score")
        enriched.append({**row, "discrepancy": abs(ranker - judge)})
    enriched.sort(key=lambda row: (-float(row["discrepancy"]), _stable_id(row)))
    return enriched[:limit]


def stratified_audit_rows(
    rows: list[dict[str, Any]],
    *,
    disagreement_count: int = 100,
    top_count: int = 50,
    bottom_count: int = 50,
) -> list[dict[str, Any]]:
    if min(disagreement_count, top_count, bottom_count) < 0:
        raise ValueError("stratum counts must be non-negative")
    if disagreement_count + top_count + bottom_count <= 0:
        raise ValueError("at least one stratum count must be positive")
    enriched = []
    for row in rows:
        ranker = _score(row, "ranker_score")
        judge = _score(row, "judge_score")
        enriched.append({**row, "discrepancy": abs(ranker - judge)})
    disagreement = sorted(enriched, key=lambda row: (-float(row["discrepancy"]), _stable_id(row)))
    top = sorted(enriched, key=lambda row: (-_score(row, "ranker_score"), _stable_id(row)))
    bottom = sorted(enriched, key=lambda row: (_score(row, "ranker_score"), _stable_id(row)))
    return _dedupe([
        *_dedupe(disagreement, disagreement_count),
        *_dedupe(top, top_count),
        *_dedupe(bottom, bottom_count),
        *disagreement,
    ], disagreement_count + top_count + bottom_count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build high-discrepancy ranking cases for human audit")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--strategy", choices=("discrepancy", "stratified"), default="discrepancy")
    parser.add_argument("--disagreement-count", type=int, default=100)
    parser.add_argument("--top-count", type=int, default=50)
    parser.add_argument("--bottom-count", type=int, default=50)
    args = parser.parse_args()
    rows = load_jsonl(args.input)
    selected = (
        stratified_audit_rows(
            rows,
            disagreement_count=args.disagreement_count,
            top_count=args.top_count,
            bottom_count=args.bottom_count,
        )
        if args.strategy == "stratified"
        else audit_rows(rows, args.limit)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for row in selected:
            target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"selected": len(selected), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
