"""Fail-closed release gate for exact-span PII benchmark reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_gate(
    report: dict[str, Any],
    *,
    minimum_coverage: float = 0.90,
    minimum_precision: float = 0.95,
    minimum_recall: float = 0.95,
    minimum_label_recall: float = 0.80,
    required_labels: tuple[str, ...] = ("EMAIL", "PHONE", "SSN", "CREDIT_CARD", "IP_ADDRESS", "API_KEY", "PASSWORD"),
) -> dict[str, Any]:
    metrics = report.get("exactSpanMetricsOnSupportedLabels", {})
    per_label = report.get("perLabel", {})
    label_checks = {
        label: isinstance(per_label.get(label, {}).get("recall"), (int, float))
        and per_label[label]["recall"] >= minimum_label_recall
        for label in required_labels
    }
    checks = {
        "taxonomy_coverage": isinstance(report.get("labelCoverage"), (int, float))
        and report["labelCoverage"] >= minimum_coverage,
        "exact_span_precision": isinstance(metrics.get("precision"), (int, float))
        and metrics["precision"] >= minimum_precision,
        "exact_span_recall": isinstance(metrics.get("recall"), (int, float))
        and metrics["recall"] >= minimum_recall,
        "required_label_recall": all(label_checks.values()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "label_checks": label_checks,
        "thresholds": {
            "minimum_coverage": minimum_coverage,
            "minimum_precision": minimum_precision,
            "minimum_recall": minimum_recall,
            "minimum_label_recall": minimum_label_recall,
        },
        "observed": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert exact-span PII release readiness")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-coverage", type=float, default=0.90)
    parser.add_argument("--minimum-precision", type=float, default=0.95)
    parser.add_argument("--minimum-recall", type=float, default=0.95)
    parser.add_argument("--minimum-label-recall", type=float, default=0.80)
    args = parser.parse_args()
    result = evaluate_gate(
        json.loads(args.input.read_text(encoding="utf-8")),
        minimum_coverage=args.minimum_coverage,
        minimum_precision=args.minimum_precision,
        minimum_recall=args.minimum_recall,
        minimum_label_recall=args.minimum_label_recall,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
