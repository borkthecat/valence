"""Convert text-only AI PII annotations into safe Label Studio silver tasks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import build_pii_tasks_from_ai_annotations, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and import AI PII annotations")
    parser.add_argument("source", type=Path, help="Offset-validated Label Studio source tasks")
    parser.add_argument("annotations", type=Path, help="AI JSON response with text-only entities")
    parser.add_argument("output", type=Path, help="Validated Label Studio silver tasks")
    parser.add_argument("--model-version", required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    if not isinstance(source, list) or not isinstance(annotations, list):
        raise ValueError("source and annotations must each contain a JSON list")
    tasks = build_pii_tasks_from_ai_annotations(source, annotations, model_version=args.model_version)
    write_json(args.output, tasks)
    print(json.dumps({"output": str(args.output), "tasks": len(tasks)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
