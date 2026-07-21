from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from hybrid_review import build_pii_ai_annotation_packet, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a blind PII AI annotation packet")
    parser.add_argument("source", type=Path, help="Offset-validated Label Studio task JSON")
    parser.add_argument("output", type=Path, help="Blind text-only JSON packet")
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    if not isinstance(source, list):
        raise ValueError("source must contain a JSON task list")
    packet = build_pii_ai_annotation_packet(source)
    write_json(args.output, packet)
    print(json.dumps({"output": str(args.output), "tasks": len(packet)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
