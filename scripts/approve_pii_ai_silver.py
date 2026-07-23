from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import audit_machine_approved_pii_tasks, machine_approve_pii_silver_tasks, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Create deterministic machine-approved PII annotations from filtered silver suggestions")
    parser.add_argument("input", type=Path, help="Validated Label Studio silver task JSON")
    parser.add_argument("output", type=Path, help="Machine-approved Label Studio annotation JSON")
    parser.add_argument("--approved-by", default="external-ai-silver-auto-approval")
    args = parser.parse_args()
    tasks = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("input must contain a JSON task list")
    approved = machine_approve_pii_silver_tasks(tasks, approved_by=args.approved_by)
    audit = audit_machine_approved_pii_tasks(approved)
    write_json(args.output, approved)
    print(json.dumps({"output": str(args.output), "audit": audit}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
