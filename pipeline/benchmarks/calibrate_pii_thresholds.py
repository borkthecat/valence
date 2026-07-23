from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def _fold(record_id: str, folds: int) -> int:
    return int(hashlib.sha256(record_id.encode("utf-8")).hexdigest()[:16], 16) % folds


def _counts(records: list[dict[str, Any]], thresholds: dict[str, float]) -> tuple[int, int, int]:
    true_positive = false_positive = false_negative = 0
    for record in records:
        truth = {(int(item["start"]), int(item["end"]), str(item["category"])) for item in record["truth"]}
        predicted = {
            (int(item["start"]), int(item["end"]), str(item["category"]))
            for item in record["predictions"]
            if float(item["score"]) >= thresholds.get(str(item["category"]), 1.0)
        }
        true_positive += len(truth & predicted)
        false_positive += len(predicted - truth)
        false_negative += len(truth - predicted)
    return true_positive, false_positive, false_negative


def _metrics(counts: tuple[int, int, int]) -> dict[str, float | int]:
    true_positive, false_positive, false_negative = counts
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "truePositive": true_positive,
        "falsePositive": false_positive,
        "falseNegative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _select_threshold(records: list[dict[str, Any]], category: str, beta: float) -> float:
    total_truth = 0
    scored: list[tuple[float, bool]] = []
    for record in records:
        truth = {(int(item["start"]), int(item["end"])) for item in record["truth"] if item["category"] == category}
        total_truth += len(truth)
        scored.extend(
            (float(item["score"]), (int(item["start"]), int(item["end"])) in truth)
            for item in record["predictions"] if item["category"] == category
        )
    scored.sort(reverse=True)
    best_score = -1.0
    best_threshold = 1.0
    beta_squared = beta * beta
    true_positive = false_positive = 0
    index = 0
    while index < len(scored):
        threshold = scored[index][0]
        while index < len(scored) and scored[index][0] == threshold:
            if scored[index][1]:
                true_positive += 1
            else:
                false_positive += 1
            index += 1
        false_negative = total_truth - true_positive
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        score = (1 + beta_squared) * precision * recall / (beta_squared * precision + recall) if precision + recall else 0.0
        if score > best_score or (score == best_score and threshold > best_threshold):
            best_score, best_threshold = score, threshold
    return best_threshold


def calibrate(records: list[dict[str, Any]], folds: int = 5, beta: float = 1.0) -> dict[str, Any]:
    if folds < 2 or len(records) < folds:
        raise ValueError("folds must be at least 2 and no greater than the record count")
    categories = sorted({str(item["category"]) for row in records for item in [*row["truth"], *row["predictions"]]})
    selected: dict[str, list[float]] = defaultdict(list)
    aggregate = [0, 0, 0]
    fold_reports = []
    for held_out in range(folds):
        training = [row for row in records if _fold(str(row["record_id"]), folds) != held_out]
        validation = [row for row in records if _fold(str(row["record_id"]), folds) == held_out]
        thresholds = {category: _select_threshold(training, category, beta) for category in categories}
        for category, threshold in thresholds.items():
            selected[category].append(threshold)
        counts = _counts(validation, thresholds)
        aggregate = [left + right for left, right in zip(aggregate, counts, strict=True)]
        fold_reports.append({"fold": held_out, "records": len(validation), "thresholds": thresholds, "metrics": _metrics(counts)})
    return {
        "method": "deterministic-record-hash-k-fold-exact-span",
        "evidencePartition": "out-of-fold",
        "folds": folds,
        "records": len(records),
        "beta": beta,
        "thresholds": {category: statistics.median(values) for category, values in selected.items()},
        "outOfFoldMetrics": _metrics(tuple(aggregate)),
        "foldReports": fold_reports,
    }


def _load(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not records:
        raise ValueError("prediction cache is empty")
    for record in records:
        if not isinstance(record.get("record_id"), str) or not isinstance(record.get("truth"), list) or not isinstance(record.get("predictions"), list):
            raise ValueError("each record requires record_id, truth, and predictions")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-validate exact-span PII classifier thresholds")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--beta", type=float, default=1.0)
    args = parser.parse_args()
    if args.beta <= 0:
        raise ValueError("--beta must be positive")
    report = calibrate(_load(args.input), args.folds, args.beta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"records": report["records"], "folds": report["folds"], **report["outOfFoldMetrics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
