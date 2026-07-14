"""Export offset-validated GLiNER PII predictions to Label Studio JSON."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from gliner_label_studio import DEFAULT_LABELS, label_studio_task


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number} must be a JSON object")
        records.append(value)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize text, run GLiNER, and export strict Label Studio spans")
    parser.add_argument("input", type=Path, help="JSONL records containing text or source_text and optional id")
    parser.add_argument("output", type=Path, help="Label Studio JSON task array")
    parser.add_argument("--model", default="urchade/gliner_multi_pii-v1")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--label", action="append", dest="labels", help="GLiNER prompt label; repeat to override defaults")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    from gliner import GLiNER

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    model = GLiNER.from_pretrained(args.model, map_location=args.device)
    labels = args.labels or DEFAULT_LABELS
    tasks = []
    for index, record in enumerate(load_jsonl(args.input)):
        raw_text = record.get("text") or record.get("source_text")
        if not isinstance(raw_text, str):
            raise ValueError(f"record {index} is missing text or source_text")
        source_id = str(record.get("id") or record.get("record_id") or f"record-{index}")
        tasks.append(label_studio_task(source_id, raw_text, model, labels, args.threshold, args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(tasks, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"tasks": len(tasks), "output": str(args.output), "model": args.model}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
