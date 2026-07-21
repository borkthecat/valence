from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import audit_pii_ai_annotations, build_pii_tasks_from_ai_annotations, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and import AI PII annotations")
    parser.add_argument("source", type=Path, help="Offset-validated Label Studio source tasks")
    parser.add_argument("annotations", type=Path, help="AI JSON response with text-only entities")
    parser.add_argument("output", type=Path, help="Validated Label Studio silver tasks")
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--discard-implausible", action="store_true")
    parser.add_argument("--quality-report", type=Path)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    annotations = json.loads(args.annotations.read_text(encoding="utf-8"))
    if not isinstance(source, list) or not isinstance(annotations, list):
        raise ValueError("source and annotations must each contain a JSON list")
    report = audit_pii_ai_annotations(source, annotations)
    tasks = build_pii_tasks_from_ai_annotations(
        source, annotations, model_version=args.model_version, discard_implausible=args.discard_implausible,
    )
    write_json(args.output, tasks)
    if args.quality_report:
        write_json(args.quality_report, report)
    print(json.dumps({"output": str(args.output), "tasks": len(tasks), "quality": report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
