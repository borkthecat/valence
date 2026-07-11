from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail CI unless every corpus meets precision and FPR release floors")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-precision", type=float, default=0.95)
    parser.add_argument("--maximum-fpr", type=float, default=0.05)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    failures = []
    for result in report.get("results", []):
        metrics = result["metrics"]
        if metrics["precision"] < args.minimum_precision or metrics["falsePositiveRate"] > args.maximum_fpr:
            failures.append({"name": result["name"], "precision": metrics["precision"], "falsePositiveRate": metrics["falsePositiveRate"]})
    payload = {"modelRef": report.get("modelRef"), "corpora": len(report.get("results", [])), "minimumPrecision": args.minimum_precision, "maximumFpr": args.maximum_fpr, "failures": failures, "passed": not failures}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True)); return 0 if payload["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
