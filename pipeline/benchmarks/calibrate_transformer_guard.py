from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from injection_corpora import SPECS
from train_transformer_guard import _metrics, _rows, _split


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate guard thresholds on training-only validation data")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--max-per-class-per-corpus", type=int, default=5_000)
    parser.add_argument("--synthetic-per-policy-class", type=int, default=2_500)
    args = parser.parse_args()
    _, validation = _split(_rows(args.cache, args.max_per_class_per_corpus, args.synthetic_per_policy_class))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        dtype=torch.float16 if device.type == "cuda" else torch.float32,
    ).to(device).eval()
    scores: list[float] = []
    for start in range(0, len(validation), args.batch_size):
        batch = tokenizer(
            [row[0] for row in validation[start:start + args.batch_size]],
            padding=True,
            truncation=True,
            max_length=args.max_length,
            return_tensors="pt",
        )
        batch = {key: value.to(device) for key, value in batch.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            probabilities = torch.softmax(model(**batch).logits.float(), dim=-1)[:, 1]
        scores.extend(probabilities.cpu().tolist())
    policies = {spec.name: spec.policy for spec in SPECS}
    thresholds: dict[str, float] = {}
    reports: dict[str, object] = {}
    for policy in sorted(set(policies.values())):
        sources = sorted(source for source, source_policy in policies.items() if source_policy == policy)
        candidates = []
        for threshold in np.linspace(0.001, 0.999, 999):
            source_metrics = {}
            floors = []
            passed = 0
            for source in sources:
                indexes = [index for index, row in enumerate(validation) if row[2] == source]
                if len(indexes) < 20:
                    continue
                metrics = _metrics(
                    [validation[index][1] for index in indexes],
                    [bool(scores[index] >= threshold) for index in indexes],
                )
                floor = min(
                    metrics["accuracy"],
                    metrics["precision"],
                    metrics["recall"],
                    metrics["f1"],
                    1 - metrics["falsePositiveRate"],
                )
                source_metrics[source] = metrics
                floors.append(float(floor))
                passed += floor >= 0.95
            candidates.append((passed, min(floors, default=0.0), sum(floors) / len(floors), -abs(threshold - 0.5), float(threshold), source_metrics))
        selected = max(candidates, key=lambda item: item[:4])
        thresholds[policy] = selected[4]
        reports[policy] = {
            "threshold": selected[4],
            "passedSources": int(selected[0]),
            "minimumFloor": float(selected[1]),
            "meanFloor": float(selected[2]),
            "sources": selected[5],
        }
    output = {"thresholds": thresholds, "validation": reports}
    (args.model / "calibration.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
