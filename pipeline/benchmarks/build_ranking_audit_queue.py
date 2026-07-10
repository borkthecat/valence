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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build high-discrepancy ranking cases for human audit")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    selected = audit_rows(load_jsonl(args.input), args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as target:
        for row in selected:
            target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"selected": len(selected), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
