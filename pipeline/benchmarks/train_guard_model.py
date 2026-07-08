from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC

from injection_corpora import fingerprint, load_corpora

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
INVISIBLE_PATTERN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
MAX_WORDS = 10_000
MAX_WORD_LENGTH = 60
MAX_CHARACTER_TEXT = 16_384


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return " ".join(INVISIBLE_PATTERN.sub("", normalized).split())


def _features(text: str) -> list[str]:
    words = [word[:MAX_WORD_LENGTH] for word in TOKEN_PATTERN.findall(_normalize(text))[:MAX_WORDS]]
    features = [f"w:{word}" for word in words]
    features.extend(f"w:{left}_{right}" for left, right in zip(words, words[1:], strict=False))
    character_text = " ".join(words)[:MAX_CHARACTER_TEXT]
    for size in (3, 4, 5):
        features.extend(f"c:{character_text[index:index + size]}" for index in range(len(character_text) - size + 1))
    return features


def _training_rows(cache: Path, max_per_class: int) -> tuple[list[tuple[str, bool]], int, int]:
    corpora = load_corpora(cache)
    test_hashes = {fingerprint(text) for corpus in corpora for text, _ in corpus.test}
    candidates: dict[bytes, list[tuple[str, bool]]] = {}
    sampled = 0
    for corpus in corpora:
        for label in (False, True):
            rows = sorted(
                (
                    (text, row_label)
                    for text, row_label in corpus.training
                    if row_label is label and fingerprint(text) not in test_hashes
                ),
                key=lambda row: fingerprint(row[0]),
            )[:max_per_class]
            sampled += len(rows)
            for row in rows:
                candidates.setdefault(fingerprint(row[0]), []).append(row)
    conflicts = 0
    training: list[tuple[str, bool]] = []
    for rows in candidates.values():
        labels = {label for _, label in rows}
        if len(labels) != 1:
            conflicts += 1
            continue
        training.append(rows[0])
    if {fingerprint(text) for text, _ in training} & test_hashes:
        raise ValueError("training/test leakage detected")
    return training, sampled - len(training) - conflicts, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the bounded Valence prompt-injection guard")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--max-features", type=int, default=150_000)
    parser.add_argument("--max-per-class-per-corpus", type=int, default=10_000)
    parser.add_argument("--class-weight", choices=("balanced", "none"), default="balanced")
    args = parser.parse_args()
    if not 10_000 <= args.max_features <= 150_000:
        raise ValueError("--max-features must be between 10000 and 150000")
    if not 100 <= args.max_per_class_per_corpus <= 25_000:
        raise ValueError("--max-per-class-per-corpus must be between 100 and 25000")
    training, duplicates, conflicts = _training_rows(args.cache, args.max_per_class_per_corpus)
    vectorizer = TfidfVectorizer(
        analyzer=_features,
        lowercase=False,
        min_df=2,
        max_features=args.max_features,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform([text for text, _ in training])
    classifier = LinearSVC(
        C=0.5,
        class_weight=None if args.class_weight == "none" else "balanced",
    ).fit(matrix, [label for _, label in training])
    names = vectorizer.get_feature_names_out()
    coefficients = classifier.coef_[0]
    features = {
        str(name): [round(float(identifier), 7), round(float(coefficient), 7)]
        for name, identifier, coefficient in zip(names, vectorizer.idf_, coefficients, strict=True)
        if not math.isclose(float(coefficient), 0.0, abs_tol=1e-12)
    }
    model = {
        "format": "valence-linear-tfidf-v1",
        "source": "15 pinned public corpora; see DATASETS.md",
        "language": "multilingual",
        "trainingRecords": len(training),
        "trainingCorpora": 15,
        "bias": round(float(classifier.intercept_[0]), 7),
        "threshold": 0.0,
        "features": dict(sorted(features.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "trainingRecords": len(training),
        "duplicatesRemoved": duplicates,
        "conflictsRemoved": conflicts,
        "features": len(features),
        "bytes": args.output.stat().st_size,
        "sha256": _sha256(args.output),
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
