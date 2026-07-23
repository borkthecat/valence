from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from gliner_label_studio import clean_text
from hybrid_review import PII_LABELS, load_jsonl, write_json


def _metrics(matched: int, predicted: int, gold: int) -> dict[str, float | int]:
    precision = matched / predicted if predicted else 0.0
    recall = matched / gold if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"matched": matched, "predicted": predicted, "gold": gold, "precision": precision, "recall": recall, "f1": f1}


def _record_id(row: dict[str, Any]) -> tuple[str, str]:
    source_id = row.get("id") or row.get("record_id")
    text = row.get("text") or row.get("source_text")
    if not isinstance(source_id, str) or not source_id or not isinstance(text, str) or not text:
        raise ValueError("source record requires stable ID and text")
    cleaned = clean_text(text)
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}", text


def evaluate(raw_rows: list[dict[str, Any]], silver_tasks: list[dict[str, Any]]) -> dict[str, Any]:
    gold_by_id: dict[str, Counter[tuple[str, str]]] = {}
    mappable_gold = 0
    skipped_gold = 0
    for raw in raw_rows:
        record_id, raw_text = _record_id(raw)
        if record_id in gold_by_id:
            raise ValueError(f"duplicate deterministic source record ID {record_id}")
        cleaned = clean_text(raw_text)
        spans: Counter[tuple[str, str]] = Counter()
        for entity in raw.get("entities", []):
            if not isinstance(entity, dict):
                continue
            label, start, end = entity.get("label"), entity.get("start"), entity.get("end")
            if not isinstance(label, str) or label not in PII_LABELS or not isinstance(start, int) or not isinstance(end, int):
                continue
            value = raw_text[start:end]
            if not 0 <= start < end <= len(raw_text) or value not in cleaned:
                skipped_gold += 1
                continue
            spans[(label, value)] += 1
            mappable_gold += 1
        gold_by_id[record_id] = spans
    predicted_by_id: dict[str, Counter[tuple[str, str]]] = {}
    for task in silver_tasks:
        data = task.get("data")
        predictions = task.get("predictions")
        if not isinstance(data, dict) or not isinstance(data.get("record_id"), str) or not isinstance(predictions, list) or len(predictions) != 1:
            raise ValueError("silver task has an invalid Label Studio structure")
        record_id = data["record_id"]
        if record_id not in gold_by_id or record_id in predicted_by_id:
            raise ValueError(f"silver task has an unknown or duplicate record ID {record_id}")
        spans: Counter[tuple[str, str]] = Counter()
        for result in predictions[0].get("result", []):
            value = result.get("value") if isinstance(result, dict) else None
            if not isinstance(value, dict):
                raise ValueError(f"silver task {record_id} has an invalid result")
            labels, text = value.get("labels"), value.get("text")
            if not isinstance(labels, list) or len(labels) != 1 or not isinstance(labels[0], str) or not isinstance(text, str):
                raise ValueError(f"silver task {record_id} has an invalid span")
            spans[(labels[0], text)] += 1
        predicted_by_id[record_id] = spans
    if set(predicted_by_id) != set(gold_by_id):
        raise ValueError("silver tasks must cover every deterministic source record exactly once")
    totals: Counter[str] = Counter()
    by_label: dict[str, Counter[str]] = defaultdict(Counter)
    for record_id, gold in gold_by_id.items():
        predicted = predicted_by_id[record_id]
        overlap = gold & predicted
        totals["matched"] += sum(overlap.values())
        totals["predicted"] += sum(predicted.values())
        totals["gold"] += sum(gold.values())
        for label in PII_LABELS:
            label_gold = Counter({key: count for key, count in gold.items() if key[0] == label})
            label_predicted = Counter({key: count for key, count in predicted.items() if key[0] == label})
            label_overlap = label_gold & label_predicted
            by_label[label]["matched"] += sum(label_overlap.values())
            by_label[label]["predicted"] += sum(label_predicted.values())
            by_label[label]["gold"] += sum(label_gold.values())
    return {
        "scope": "benchmark_only_text_and_label_multiset_overlap",
        "records": len(raw_rows),
        "mappable_gold_spans": mappable_gold,
        "skipped_unmappable_gold_spans": skipped_gold,
        "overall": _metrics(totals["matched"], totals["predicted"], totals["gold"]),
        "by_label": {label: _metrics(values["matched"], values["predicted"], values["gold"]) for label, values in sorted(by_label.items())},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AI PII silver labels against a labeled benchmark without altering tasks")
    parser.add_argument("source", type=Path)
    parser.add_argument("silver_tasks", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    silver_tasks = json.loads(args.silver_tasks.read_text(encoding="utf-8"))
    if not isinstance(silver_tasks, list):
        raise ValueError("silver_tasks must contain a JSON task list")
    report = evaluate(load_jsonl(args.source), silver_tasks)
    write_json(args.output, report)
    print(json.dumps(report["overall"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
