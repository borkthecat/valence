from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .harvest_shadow_negatives import redact_pii
except ImportError:
    from harvest_shadow_negatives import redact_pii


TARGET_SOURCES = frozenset(("hse_llm", "cgoosen_combined"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")


def _record_id(source: str, text: str) -> str:
    return hashlib.sha256(f"{source}\0{text}".encode("utf-8")).hexdigest()


def capture(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a privacy-reduced, deduplicated review queue from shadow events."""
    selected: dict[str, dict[str, Any]] = {}
    for event in events:
        source = event.get("source") or event.get("source_id")
        text = event.get("text") or event.get("content")
        if source not in TARGET_SOURCES or not isinstance(text, str) or not text.strip():
            continue
        sanitized = redact_pii(text).strip()
        record_id = _record_id(source, sanitized)
        score = event.get("score")
        selected.setdefault(record_id, {
            "record_id": record_id,
            "source": source,
            "text": sanitized,
            "model_score": float(score) if isinstance(score, int | float) else None,
            "route": "review",
        })
    return sorted(selected.values(), key=lambda row: (row["source"], -float(row["model_score"] or 0), row["record_id"]))


def merge_labels(queue: list[dict[str, Any]], labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join explicit human labels; reject missing, duplicate, or invalid decisions."""
    decisions: dict[str, bool] = {}
    for label in labels:
        record_id, value = label.get("record_id"), label.get("label")
        if not isinstance(record_id, str) or not isinstance(value, bool):
            raise ValueError("each label requires string record_id and boolean label")
        if record_id in decisions:
            raise ValueError(f"duplicate human label for {record_id}")
        decisions[record_id] = value
    queue_ids = {str(row["record_id"]) for row in queue}
    unknown = set(decisions) - queue_ids
    if unknown:
        raise ValueError(f"labels refer to unknown records: {sorted(unknown)[:3]}")
    return [{"record_id": row["record_id"], "source": row["source"], "label": decisions[row["record_id"]], "text": row["text"], "origin": "shadow_human_review"}
            for row in queue if row["record_id"] in decisions]


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture and label privacy-reduced provenance-guard shadow traffic")
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--events", type=Path, required=True)
    capture_parser.add_argument("--output", type=Path, required=True)
    labels_parser = commands.add_parser("merge-labels")
    labels_parser.add_argument("--queue", type=Path, required=True)
    labels_parser.add_argument("--labels", type=Path, required=True)
    labels_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = capture(_read_jsonl(args.events)) if args.command == "capture" else merge_labels(_read_jsonl(args.queue), _read_jsonl(args.labels))
    _write_jsonl(args.output, rows)
    print(json.dumps({"command": args.command, "records": len(rows), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
