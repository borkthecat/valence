from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a risk-calibrated guard operating standard")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    totals = {key: sum(item["metrics"][key] for item in report["results"]) for key in ("samples", "truePositive", "trueNegative", "falsePositive", "falseNegative")}
    tp, tn, fp, fn = (totals[key] for key in ("truePositive", "trueNegative", "falsePositive", "falseNegative"))
    precision = tp / max(1, tp + fp); recall = tp / max(1, tp + fn)
    metrics = {"accuracy": (tp + tn) / totals["samples"], "precision": precision, "recall": recall, "f1": 2 * precision * recall / max(1e-12, precision + recall), "falsePositiveRate": fp / max(1, fp + tn)}
    global_limits = {
        "minAccuracy": ("accuracy", "minimum"),
        "minPrecision": ("precision", "minimum"),
        "minRecall": ("recall", "minimum"),
        "minF1": ("f1", "minimum"),
        "maxFalsePositiveRate": ("falsePositiveRate", "maximum"),
    }
    failures = []
    for profile_key, (metric_key, direction) in global_limits.items():
        target = profile["global"][profile_key]
        if (direction == "minimum" and metrics[metric_key] < target) or (direction == "maximum" and metrics[metric_key] > target):
            failures.append({"metric": metric_key, "actual": metrics[metric_key], "target": target})
    source_actions = []
    for item in report["results"]:
        source = item["name"]; source_metrics = item["metrics"]
        if source_metrics["falsePositiveRate"] > profile["maxSourceFalsePositiveRate"]:
            failures.append({"source": source, "metric": "falsePositiveRate", "actual": source_metrics["falsePositiveRate"], "target": profile["maxSourceFalsePositiveRate"]})
        mode = "enforce" if source_metrics["recall"] >= profile["minimumEnforceRecall"] else "review"
        source_actions.append({"source": source, "mode": mode, "metrics": source_metrics})
    payload = {"profile": profile["name"], "report": str(args.report), "metrics": metrics, "sourceActions": source_actions, "passed": not failures, "failures": failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": payload["passed"], "metrics": metrics, "reviewSources": [item["source"] for item in source_actions if item["mode"] == "review"]}))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
