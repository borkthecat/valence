from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from injection_corpora import fingerprint, load_corpus, policy_text
from train_transformer_guard import _metrics
from moe_guard import EXPERT_SOURCES


def _split_rows(source: str, cache: Path, per_label: int) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    corpus = load_corpus(cache, source); test_hashes = {fingerprint(text) for text, _ in corpus.test}
    groups = {False: [], True: []}
    for text, label in corpus.training:
        if fingerprint(text) not in test_hashes: groups[label].append((policy_text(text, corpus.spec.policy), label))
    train, calibration = [], []
    for label, rows in groups.items():
        rows.sort(key=lambda row: fingerprint(row[0])); rows = rows[:per_label]
        calibration.extend(row for row in rows if fingerprint(row[0])[-1] < 64)
        train.extend(row for row in rows if fingerprint(row[0])[-1] >= 64)
    if not all(any(label == expected for _, label in part) for part in (train, calibration) for expected in (False, True)):
        raise ValueError(f"{source} lacks both labels after split")
    return train, calibration


def _embeddings(model: object, tokenizer: object, rows: list[tuple[str, bool]], device: torch.device, batch_size: int) -> np.ndarray:
    vectors = []
    for start in range(0, len(rows), batch_size):
        encoded = tokenizer([text for text, _ in rows[start:start + batch_size]], padding=True, truncation=True, max_length=256, return_tensors="pt")
        batch = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=device.type == "cuda"):
            hidden = model(**batch, output_hidden_states=True).hidden_states[-1][:, 0, :]
        vectors.append(hidden.float().cpu().numpy())
    return np.concatenate(vectors)


def _threshold(scores: np.ndarray, labels: list[bool]) -> tuple[float, bool]:
    candidates = []
    for value in np.arange(0.01, 0.991, 0.005):
        metrics = _metrics(labels, [score >= value for score in scores])
        if metrics["precision"] >= 0.95 and metrics["falsePositiveRate"] <= 0.05: candidates.append(float(value))
    return (min(candidates), True) if candidates else (0.5, False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train frozen-V6 source-specific logistic experts")
    parser.add_argument("--model", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface")); parser.add_argument("--per-label", type=int, default=1000); parser.add_argument("--batch-size", type=int, default=16)
    args = parser.parse_args()
    if not torch.cuda.is_available(): raise RuntimeError("CUDA is required for frozen embedding extraction")
    tokenizer = AutoTokenizer.from_pretrained(args.model); model = AutoModelForSequenceClassification.from_pretrained(args.model, dtype=torch.float16).to("cuda").eval()
    for parameter in model.parameters(): parameter.requires_grad_(False)
    device = torch.device("cuda"); args.output.mkdir(parents=True, exist_ok=True); registry: dict[str, object] = {"baseModel": str(args.model), "experts": {}}
    for source in sorted(EXPERT_SOURCES):
        train, calibration = _split_rows(source, args.cache, args.per_label)
        classifier = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=20260711).fit(_embeddings(model, tokenizer, train, device, args.batch_size), [label for _, label in train])
        scores = classifier.predict_proba(_embeddings(model, tokenizer, calibration, device, args.batch_size))[:, 1]
        threshold, calibrated = _threshold(scores, [label for _, label in calibration])
        artifact = args.output / f"{source}.joblib"; joblib.dump({"classifier": classifier, "threshold": threshold}, artifact)
        registry["experts"][source] = {"artifact": artifact.name, "threshold": threshold, "calibrationGateSatisfied": calibrated, "trainRecords": len(train), "calibrationRecords": len(calibration)}
        (args.output / "registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"source": source, "threshold": threshold, "calibrationGateSatisfied": calibrated}), flush=True)
        gc.collect(); torch.cuda.empty_cache()
    return 0


if __name__ == "__main__": raise SystemExit(main())
