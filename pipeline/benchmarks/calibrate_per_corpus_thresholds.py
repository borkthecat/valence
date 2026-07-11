from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from injection_corpora import SPECS, fingerprint, load_corpus, policy_text
from train_transformer_guard import _metrics


def _json_default(value: object) -> object:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate V6 thresholds independently for each source corpus")
    parser.add_argument("--model", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface")); parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=256); parser.add_argument("--step", type=float, default=0.005)
    parser.add_argument("--minimum-precision", type=float, default=0.95); parser.add_argument("--maximum-fpr", type=float, default=0.05)
    args = parser.parse_args()
    if not 0 < args.step <= 0.1: raise ValueError("step must be in (0, 0.1]")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, dtype=torch.float16 if device.type == "cuda" else torch.float32).to(device).eval()
    grid = np.arange(0.01, 0.9901, args.step)
    sources: dict[str, dict[str, object]] = {}
    thresholds: dict[str, float] = {}
    for spec in SPECS:
        print(json.dumps({"source": spec.name, "status": "scoring"}), flush=True)
        corpus = load_corpus(args.cache, spec.name)
        test_hashes = {fingerprint(text) for text, _ in corpus.test}
        candidates = [(policy_text(text, spec.policy), label) for text, label in corpus.training if fingerprint(text) not in test_hashes and fingerprint(policy_text(text, spec.policy))[-1] < 26]
        candidates.sort(key=lambda row: fingerprint(row[0]))
        candidates = candidates[:10_000]
        labels = [label for _, label in candidates]
        source_scores: list[float] = []
        for start in range(0, len(candidates), args.batch_size):
            batch = tokenizer([text for text, _ in candidates[start:start + args.batch_size]], padding=True, truncation=True, max_length=args.max_length, return_tensors="pt")
            batch = {key: value.to(device) for key, value in batch.items()}
            with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
                source_scores.extend(torch.softmax(model(**batch).logits.float(), dim=-1)[:, 1].cpu().tolist())
        threshold_candidates = []
        for threshold in grid:
            metrics = _metrics(labels, [score >= threshold for score in source_scores])
            if metrics["precision"] >= args.minimum_precision and metrics["falsePositiveRate"] <= args.maximum_fpr:
                threshold_candidates.append((float(threshold), metrics))
        selected = min(threshold_candidates, key=lambda item: item[0]) if threshold_candidates else None
        sources[spec.name] = {"samples": len(candidates), "threshold": None if selected is None else selected[0], "metrics": None if selected is None else selected[1], "gateSatisfied": selected is not None}
        if selected is not None: thresholds[spec.name] = selected[0]
        partial = {"model": str(args.model), "partition": "train-excluded validation", "step": args.step, "minimumPrecision": args.minimum_precision, "maximumFpr": args.maximum_fpr, "thresholds": thresholds, "sources": sources, "allSourcesSatisfied": False, "partial": True}
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(partial, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
        print(json.dumps({"source": spec.name, "status": "complete", "gateSatisfied": selected is not None}), flush=True)
    payload = {"model": str(args.model), "partition": "train-excluded validation", "step": args.step, "minimumPrecision": args.minimum_precision, "maximumFpr": args.maximum_fpr, "thresholds": thresholds, "sources": sources, "allSourcesSatisfied": len(thresholds) == len(sources)}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")
    print(json.dumps({"sources": len(sources), "satisfied": len(thresholds), "allSourcesSatisfied": payload["allSourcesSatisfied"]}, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
