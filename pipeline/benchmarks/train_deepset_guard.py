from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DATASET = "deepset/prompt-injections"
API = "https://datasets-server.huggingface.co/rows"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _features(text: str) -> list[str]:
    words = TOKEN_PATTERN.findall(text.casefold())[:10_000]
    return words + [f"{left}_{right}" for left, right in zip(words, words[1:], strict=False)]


def _fetch() -> list[tuple[str, bool]]:
    rows: list[tuple[str, bool]] = []
    for offset in range(0, 10_000, 100):
        query = urllib.parse.urlencode({
            "dataset": DATASET,
            "config": "default",
            "split": "train",
            "offset": offset,
            "length": 100,
        })
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Valence-Guard-Training"})
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)["rows"]
        rows.extend((str(item["row"]["text"]), bool(item["row"]["label"])) for item in page)
        if len(page) < 100:
            break
    return rows


def _fit(rows: list[tuple[str, bool]], max_features: int) -> tuple[float, dict[str, float]]:
    counts = {False: Counter[str](), True: Counter[str]()}
    documents = Counter(label for _, label in rows)
    for text, label in rows:
        counts[label].update(_features(text))
    combined = counts[False] + counts[True]
    vocabulary = {
        token for token, count in combined.most_common(max_features) if count >= 2
    }
    size = len(vocabulary)
    totals = {
        label: sum(counts[label][token] for token in vocabulary)
        for label in (False, True)
    }
    weights = {
        token: round(
            math.log((counts[True][token] + 1) / (totals[True] + size))
            - math.log((counts[False][token] + 1) / (totals[False] + size)),
            8,
        )
        for token in vocabulary
    }
    bias = math.log(documents[True] / documents[False])
    return bias, weights


def _score(text: str, bias: float, weights: dict[str, float]) -> float:
    return bias + sum(weights.get(feature, 0.0) for feature in _features(text))


def _threshold(rows: list[tuple[str, bool]], bias: float, weights: dict[str, float]) -> float:
    scored = sorted((_score(text, bias, weights), label) for text, label in rows)
    candidates = [value for value, _ in scored]
    best = (0.0, 0.0)
    for threshold in candidates:
        true_positive = sum(score >= threshold and label for score, label in scored)
        false_positive = sum(score >= threshold and not label for score, label in scored)
        false_negative = sum(score < threshold and label for score, label in scored)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best[0]:
            best = (f1, threshold)
    return best[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a bounded guard model on deepset's training split")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-features", type=int, default=10_000)
    args = parser.parse_args()
    if not 100 <= args.max_features <= 20_000:
        raise ValueError("--max-features must be between 100 and 20000")
    rows = _fetch()
    training = []
    validation = []
    for row in rows:
        bucket = hashlib.sha256(row[0].encode("utf-8")).digest()[0]
        (validation if bucket < 51 else training).append(row)
    validation_bias, validation_weights = _fit(training, args.max_features)
    threshold = _threshold(validation, validation_bias, validation_weights)
    bias, weights = _fit(rows, args.max_features)
    model = {
        "format": "valence-multinomial-nb-v1",
        "source": f"{DATASET}@train",
        "bias": round(bias, 8),
        "threshold": round(threshold, 8),
        "weights": dict(sorted(weights.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "records": len(rows),
        "training": len(training),
        "validation": len(validation),
        "features": len(weights),
        "threshold": threshold,
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
