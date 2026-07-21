"""Verify that Label Studio PII task offsets match their displayed text exactly."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import audit_pii_label_studio_tasks


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Label Studio PII task integrity")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    tasks = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(tasks, list):
        raise ValueError("input must contain a JSON task list")
    print(json.dumps(audit_pii_label_studio_tasks(tasks), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
