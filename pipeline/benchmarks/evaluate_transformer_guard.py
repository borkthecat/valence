from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from injection_corpora import policy_text


def _metrics(labels: list[bool], predictions: list[bool]) -> dict[str, float | int]:
    tp = sum(label and prediction for label, prediction in zip(labels, predictions))
    tn = sum(not label and not prediction for label, prediction in zip(labels, predictions))
    fp = sum(not label and prediction for label, prediction in zip(labels, predictions))
    fn = sum(label and not prediction for label, prediction in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "samples": len(labels),
        "truePositive": tp,
        "trueNegative": tn,
        "falsePositive": fp,
        "falseNegative": fn,
        "accuracy": (tp + tn) / len(labels) if labels else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "falsePositiveRate": fp / (fp + tn) if fp + tn else 0.0,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a transformer guard against the pinned corpus matrix")
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--minimum", type=float, default=0.95)
    parser.add_argument("--maximum-fpr", type=float, default=0.05)
    parser.add_argument("--calibration", type=Path)
    args = parser.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        dtype=torch.float16 if device.type == "cuda" else torch.float32,
    ).to(device).eval()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    calibration_path = args.calibration or args.model / "calibration.json"
    thresholds = {"direct": 0.5, "indirect": 0.5, "secret": 0.5}
    if calibration_path.exists():
        thresholds.update(json.loads(calibration_path.read_text(encoding="utf-8"))["thresholds"])
    results: list[dict[str, Any]] = []
    totals: list[tuple[bool, bool]] = []
    for corpus in matrix:
        rows = [json.loads(line) for line in Path(corpus["fixture"]).read_text(encoding="utf-8").splitlines()]
        predictions: list[bool] = []
        for start in range(0, len(rows), args.batch_size):
            batch = tokenizer(
                [policy_text(row["text"], corpus["policy"]) for row in rows[start:start + args.batch_size]],
                padding=True,
                truncation=True,
                max_length=args.max_length,
                return_tensors="pt",
            )
            batch = {key: value.to(device) for key, value in batch.items()}
            with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                probabilities = torch.softmax(model(**batch).logits.float(), dim=-1)[:, 1].cpu().tolist()
                predictions.extend(value >= thresholds[corpus["policy"]] for value in probabilities)
        labels = [bool(row["label"]) for row in rows]
        metrics = _metrics(labels, predictions)
        passed = (
            all(metrics[key] >= args.minimum for key in ("accuracy", "precision", "recall", "f1"))
            and metrics["falsePositiveRate"] <= args.maximum_fpr
        )
        results.append({**corpus, "passed": passed, "metrics": metrics})
        totals.extend(zip(labels, predictions))
        print(json.dumps({"name": corpus["name"], "passed": passed, "metrics": metrics}), flush=True)
    summary = {
        "corpora": len(results),
        "passed": sum(result["passed"] for result in results),
        "failed": sum(not result["passed"] for result in results),
        "modelSha256": _sha256(args.model / "model.safetensors"),
        "minimum": args.minimum,
        "maximumFpr": args.maximum_fpr,
        "thresholds": thresholds,
        "pooledMetrics": _metrics([label for label, _ in totals], [prediction for _, prediction in totals]),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("corpora", "passed", "failed")}), flush=True)
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
