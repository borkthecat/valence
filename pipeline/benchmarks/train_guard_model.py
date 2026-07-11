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

from injection_corpora import fingerprint, load_corpora, policy_text

TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
INVISIBLE_PATTERN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
MAX_WORDS = 10_000
MAX_WORD_LENGTH = 60
MAX_CHARACTER_TEXT = 16_384
POLICIES = ("direct", "indirect", "secret")


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


def _metrics(labels: list[bool], predictions: list[bool]) -> dict[str, float]:
    true_positive = sum(label and prediction for label, prediction in zip(labels, predictions, strict=True))
    true_negative = sum(not label and not prediction for label, prediction in zip(labels, predictions, strict=True))
    false_positive = sum(not label and prediction for label, prediction in zip(labels, predictions, strict=True))
    false_negative = sum(label and not prediction for label, prediction in zip(labels, predictions, strict=True))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    false_positive_rate = false_positive / (true_negative + false_positive) if true_negative + false_positive else 0.0
    accuracy = (true_positive + true_negative) / len(labels) if labels else 0.0
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "falsePositiveRate": false_positive_rate,
    }


def _threshold_score(metrics: dict[str, float]) -> float:
    return min(
        metrics["accuracy"],
        metrics["precision"],
        metrics["recall"],
        metrics["f1"],
        1.0 - metrics["falsePositiveRate"],
    )


def _calibrate_thresholds(
    scores: list[tuple[float, bool, str]],
    default_threshold: float,
) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    for policy in POLICIES:
        rows = [(score, label) for score, label, row_policy in scores if row_policy == policy]
        if not rows:
            thresholds[policy] = default_threshold
            continue
        candidates = {default_threshold}
        candidates.update(round(score, 4) for score, _ in rows)
        candidates.update(round(score + 1e-4, 4) for score, _ in rows)
        best_threshold = default_threshold
        best_score = -1.0
        labels = [label for _, label in rows]
        for threshold in sorted(candidates):
            predictions = [score >= threshold for score, _ in rows]
            metrics = _metrics(labels, predictions)
            score = _threshold_score(metrics)
            if score > best_score or (math.isclose(score, best_score) and abs(threshold) < abs(best_threshold)):
                best_score = score
                best_threshold = threshold
        thresholds[policy] = best_threshold
    return thresholds


def _extra_rows(paths: list[Path]) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError(f"{path}:{line_number} must contain an object")
                text = record.get("text")
                label = record.get("label")
                policy = record.get("policy", "direct")
                if not isinstance(text, str) or not isinstance(label, bool) or policy not in POLICIES:
                    raise ValueError(f"{path}:{line_number} needs text, boolean label, and valid policy")
                rows.append((policy_text(text, str(policy)), label, str(policy)))
    return rows


def _dedupe_training_rows(rows: list[tuple[str, bool, str]]) -> tuple[list[tuple[str, bool, str]], int]:
    candidates: dict[bytes, list[tuple[str, bool, str]]] = {}
    for row in rows:
        candidates.setdefault(fingerprint(row[0]), []).append(row)
    selected = []
    conflicts = 0
    for duplicates in candidates.values():
        if len({row[1] for row in duplicates}) != 1:
            conflicts += 1
            continue
        selected.append(duplicates[0])
    return sorted(selected, key=lambda row: fingerprint(row[0])), conflicts


def _training_rows(
    cache: Path,
    max_per_class: int,
    extra_jsonl: list[Path],
    extra_calibration_jsonl: list[Path],
) -> tuple[list[tuple[str, bool, str]], list[tuple[str, bool, str]], int, int, int, int]:
    corpora = load_corpora(cache)
    test_hashes = {fingerprint(text) for corpus in corpora for text, _ in corpus.test}
    candidates: dict[bytes, list[tuple[str, bool, str]]] = {}
    sampled = 0
    for corpus in corpora:
        for label in (False, True):
            rows = sorted(
                (
                    (policy_text(text, corpus.spec.policy), row_label, corpus.spec.policy)
                    for text, row_label in corpus.training
                    if row_label is label and fingerprint(text) not in test_hashes
                ),
                key=lambda row: fingerprint(row[0]),
            )[:max_per_class]
            sampled += len(rows)
            for row in rows:
                candidates.setdefault(fingerprint(row[0]), []).append(row)
    conflicts = 0
    training: list[tuple[str, bool, str]] = []
    calibration: list[tuple[str, bool, str]] = []
    for rows in candidates.values():
        labels = {label for _, label, _ in rows}
        if len(labels) != 1:
            conflicts += 1
            continue
        row = rows[0]
        if fingerprint(row[0])[-1] < 26:
            calibration.append(row)
        else:
            training.append(row)
    base_training_records = len(training)
    public_duplicates = sampled - base_training_records - len(calibration) - conflicts
    extra_training = _extra_rows(extra_jsonl)
    extra_calibration = _extra_rows(extra_calibration_jsonl)
    if {fingerprint(text) for text, _, _ in [*extra_training, *extra_calibration]} & test_hashes:
        raise ValueError("extra training/test leakage detected")
    training, extra_conflicts = _dedupe_training_rows([*training, *extra_training])
    conflicts += extra_conflicts
    if {fingerprint(text) for text, _, _ in training} & test_hashes:
        raise ValueError("training/test leakage detected")
    calibration, extra_calibration_conflicts = _dedupe_training_rows([*calibration, *extra_calibration])
    conflicts += extra_calibration_conflicts
    if {fingerprint(text) for text, _, _ in calibration} & test_hashes:
        raise ValueError("calibration/test leakage detected")
    return training, calibration, public_duplicates, conflicts, len(extra_training), len(extra_calibration)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the bounded Valence prompt-injection guard")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".benchmark-data/huggingface"))
    parser.add_argument("--max-features", type=int, default=150_000)
    parser.add_argument("--max-per-class-per-corpus", type=int, default=10_000)
    parser.add_argument("--class-weight", choices=("balanced", "none"), default="balanced")
    parser.add_argument("--extra-jsonl", type=Path, action="append", default=[], help="Additional training-only JSONL records with text, label, and policy")
    parser.add_argument("--extra-calibration-jsonl", type=Path, action="append", default=[], help="Additional calibration-only JSONL records with text, label, and policy")
    args = parser.parse_args()
    if not 10_000 <= args.max_features <= 150_000:
        raise ValueError("--max-features must be between 10000 and 150000")
    if not 100 <= args.max_per_class_per_corpus <= 25_000:
        raise ValueError("--max-per-class-per-corpus must be between 100 and 25000")
    training, calibration, duplicates, conflicts, extra_records, extra_calibration_records = _training_rows(
        args.cache,
        args.max_per_class_per_corpus,
        args.extra_jsonl,
        args.extra_calibration_jsonl,
    )
    vectorizer = TfidfVectorizer(
        analyzer=_features,
        lowercase=False,
        min_df=2,
        max_features=args.max_features,
        sublinear_tf=True,
        norm="l2",
    )
    matrix = vectorizer.fit_transform([text for text, _, _ in training])
    classifier = LinearSVC(
        C=0.5,
        class_weight=None if args.class_weight == "none" else "balanced",
    ).fit(matrix, [label for _, label, _ in training])
    calibration_matrix = vectorizer.transform([text for text, _, _ in calibration])
    calibration_scores = [
        (float(score), label, policy)
        for score, (_, label, policy) in zip(classifier.decision_function(calibration_matrix), calibration, strict=True)
    ]
    policy_thresholds = _calibrate_thresholds(calibration_scores, 0.0)
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
        "calibrationRecords": len(calibration),
        "trainingCorpora": 15,
        "policyAware": True,
        "policyThresholds": policy_thresholds,
        "bias": round(float(classifier.intercept_[0]), 7),
        "threshold": 0.0,
        "features": dict(sorted(features.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({
        "trainingRecords": len(training),
        "calibrationRecords": len(calibration),
        "extraTrainingRecords": extra_records,
        "extraCalibrationRecords": extra_calibration_records,
        "policyThresholds": policy_thresholds,
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
