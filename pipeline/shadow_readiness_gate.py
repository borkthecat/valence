"""Fail-closed release gate for a human-reviewed shadow-run report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_gate(
    report: dict[str, Any],
    *,
    minimum_cases: int = 1_000,
    minimum_precision: float = 0.95,
    minimum_recall: float = 0.95,
    minimum_agreement: float = 0.95,
    maximum_p95_latency_ms: float = 2_000,
) -> dict[str, Any]:
    latency = report.get("latency_ms", {})
    checks = {
        "minimum_cases": int(report.get("classified_comparisons", 0)) >= minimum_cases,
        "review_precision": isinstance(report.get("review_precision"), (int, float))
        and report["review_precision"] >= minimum_precision,
        "review_recall": isinstance(report.get("review_recall"), (int, float))
        and report["review_recall"] >= minimum_recall,
        "comparison_agreement": isinstance(report.get("comparison_agreement"), (int, float))
        and report["comparison_agreement"] >= minimum_agreement,
        "p95_latency": isinstance(latency, dict)
        and isinstance(latency.get("p95"), (int, float))
        and latency["p95"] <= maximum_p95_latency_ms,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": {
            "minimum_cases": minimum_cases,
            "minimum_precision": minimum_precision,
            "minimum_recall": minimum_recall,
            "minimum_agreement": minimum_agreement,
            "maximum_p95_latency_ms": maximum_p95_latency_ms,
        },
        "observed": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert the production shadow-readiness gate")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-cases", type=int, default=1_000)
    parser.add_argument("--minimum-precision", type=float, default=0.95)
    parser.add_argument("--minimum-recall", type=float, default=0.95)
    parser.add_argument("--minimum-agreement", type=float, default=0.95)
    parser.add_argument("--maximum-p95-latency-ms", type=float, default=2_000)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    result = evaluate_gate(
        report,
        minimum_cases=args.minimum_cases,
        minimum_precision=args.minimum_precision,
        minimum_recall=args.minimum_recall,
        minimum_agreement=args.minimum_agreement,
        maximum_p95_latency_ms=args.maximum_p95_latency_ms,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
