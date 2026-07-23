from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import build_pii_ai_annotation_source, load_jsonl, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic normalized PII AI annotation source tasks")
    parser.add_argument("input", type=Path, help="JSONL source records with stable IDs and text")
    parser.add_argument("output", type=Path, help="Normalized Label Studio source task JSON")
    parser.add_argument("--expected-annotations", type=Path)
    args = parser.parse_args()
    tasks = build_pii_ai_annotation_source(load_jsonl(args.input))
    if args.expected_annotations:
        annotations = json.loads(args.expected_annotations.read_text(encoding="utf-8"))
        if not isinstance(annotations, list):
            raise ValueError("expected annotations must contain a JSON list")
        expected = {row.get("record_id") for row in annotations if isinstance(row, dict)}
        actual = {task["data"]["record_id"] for task in tasks}
        if expected != actual:
            raise ValueError("normalized source record IDs do not match the supplied annotations")
    write_json(args.output, tasks)
    print(json.dumps({"output": str(args.output), "tasks": len(tasks)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
