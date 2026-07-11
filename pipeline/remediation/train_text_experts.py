from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

ROOT = Path(__file__).resolve().parents[1] / "benchmarks"
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from injection_corpora import fingerprint, load_corpus, policy_text
from train_transformer_guard import _metrics
from moe_guard import EXPERT_SOURCES


def _rows(source: str, cache: Path, per_label: int, augmentation: list[dict[str, object]] | None = None) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    corpus = load_corpus(cache, source); test = {fingerprint(text) for text, _ in corpus.test}; groups = {False: [], True: []}
    for text, label in corpus.training:
        if fingerprint(text) not in test: groups[label].append((policy_text(text, corpus.spec.policy), label))
    train, calibration = [], []
    for label, group in groups.items():
        group.sort(key=lambda row: fingerprint(row[0])); group = group[:per_label]
        calibration.extend(row for row in group if fingerprint(row[0])[-1] < 64); train.extend(row for row in group if fingerprint(row[0])[-1] >= 64)
    known = {fingerprint(text) for text, _ in train + calibration}
    for row in augmentation or []:
        text = row.get("text")
        if row.get("source") == source and row.get("label") is False and isinstance(text, str) and fingerprint(text) not in known:
            train.append((policy_text(text, corpus.spec.policy), False)); known.add(fingerprint(text))
    return train, calibration


def _pipeline() -> Pipeline:
    return Pipeline([("features", FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=30_000, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=30_000, sublinear_tf=True)),
    ])), ("classifier", LogisticRegression(class_weight="balanced", max_iter=3000, random_state=20260711))])


def _threshold(
    scores: list[float], labels: list[bool], minimum_precision: float, maximum_fpr: float
) -> tuple[float, bool]:
    valid = []
    for threshold in np.arange(0.01, 0.991, 0.005):
        metrics = _metrics(labels, [score >= threshold for score in scores])
        if metrics["precision"] >= minimum_precision and metrics["falsePositiveRate"] <= maximum_fpr: valid.append(float(threshold))
    if valid: return min(valid), True
    best = max(((_metrics(labels, [score >= threshold for score in scores])["f1"], float(threshold)) for threshold in np.arange(0.01, 0.991, 0.005)), key=lambda item: item[0])
    return best[1], False


def main() -> int:
    parser = argparse.ArgumentParser(description="Train source-specific lexical/character experts without touching V6")
    parser.add_argument("--output", type=Path, required=True); parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface")); parser.add_argument("--per-label", type=int, default=2000)
    parser.add_argument("--minimum-precision", type=float, default=0.95); parser.add_argument("--maximum-fpr", type=float, default=0.05)
    parser.add_argument("--augmentation", type=Path)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True); registry = {"baseModel": "v6-global-fallback", "experts": {}}
    augmentation = [json.loads(line) for line in args.augmentation.read_text(encoding="utf-8").splitlines() if line.strip()] if args.augmentation else []
    for source in sorted(EXPERT_SOURCES):
        train, calibration = _rows(source, args.cache, args.per_label, augmentation)
        if not train or not calibration or len({label for _, label in train}) < 2 or len({label for _, label in calibration}) < 2: raise ValueError(f"invalid source split: {source}")
        model = _pipeline().fit([text for text, _ in train], [label for _, label in train]); scores = model.predict_proba([text for text, _ in calibration])[:, 1].tolist(); threshold, passed = _threshold(scores, [label for _, label in calibration], args.minimum_precision, args.maximum_fpr)
        artifact = args.output / f"{source}.joblib"; joblib.dump({"kind": "text", "classifier": model, "threshold": threshold}, artifact)
        registry["experts"][source] = {"artifact": artifact.name, "kind": "text", "threshold": threshold, "calibrationGateSatisfied": passed, "trainRecords": len(train), "calibrationRecords": len(calibration)}
        (args.output / "registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print(json.dumps({"source": source, "threshold": threshold, "calibrationGateSatisfied": passed}), flush=True); gc.collect()
    return 0


if __name__ == "__main__": raise SystemExit(main())
