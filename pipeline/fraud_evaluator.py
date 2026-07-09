from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MAX_DATASET_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FraudEvaluation:
    records: int
    fraudulent: int
    threshold: float
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    unmitigated_fer_at_k: float
    risk_adjusted_fer_at_k: float


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("fraud dataset exceeds 512 MiB")
    records = []
    with path.open("rb") as source:
        for line_number, raw_line in enumerate(source, 1):
            if len(raw_line) > MAX_LINE_BYTES:
                raise ValueError(f"line {line_number} exceeds 5 MiB")
            if not raw_line.strip():
                continue
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} must contain an object")
            records.append(value)
    if not records:
        raise ValueError("fraud dataset is empty")
    return records


def _is_fraud(record: dict[str, Any]) -> bool:
    value = record.get("fraudulent")
    if not isinstance(value, bool):
        raise ValueError("each record requires boolean fraudulent")
    return value


def _score(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"each record requires numeric {key}")
    return float(value)


def evaluate(records: list[dict[str, Any]], threshold: float, top_k: int, risk_penalty: float) -> FraudEvaluation:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    tp = tn = fp = fn = 0
    for record in records:
        label = _is_fraud(record)
        predicted = _score(record, "risk_score") >= threshold
        if predicted and label:
            tp += 1
        elif not predicted and not label:
            tn += 1
        elif predicted:
            fp += 1
        else:
            fn += 1
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    unmitigated = sorted(records, key=lambda item: _score(item, "source_relevance_score"), reverse=True)[:top_k]
    adjusted = sorted(
        records,
        key=lambda item: _score(item, "source_relevance_score") - risk_penalty * _score(item, "risk_score"),
        reverse=True,
    )[:top_k]
    return FraudEvaluation(
        records=len(records),
        fraudulent=sum(_is_fraud(record) for record in records),
        threshold=threshold,
        true_positive=tp,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        false_positive_rate=_ratio(fp, fp + tn),
        unmitigated_fer_at_k=_ratio(sum(_is_fraud(record) for record in unmitigated), len(unmitigated)),
        risk_adjusted_fer_at_k=_ratio(sum(_is_fraud(record) for record in adjusted), len(adjusted)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate EMSCAD-style fraud risk and Fraud Exposure Rate")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--risk-penalty", type=float, default=0.5)
    parser.add_argument("--max-fer", type=float)
    args = parser.parse_args()
    report = evaluate(load_jsonl(args.dataset), args.threshold, args.top_k, args.risk_penalty)
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    if args.max_fer is not None and report.risk_adjusted_fer_at_k > args.max_fer:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
