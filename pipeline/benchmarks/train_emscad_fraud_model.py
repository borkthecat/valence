from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from export_emscad import TEXT_FIELDS, map_row


STRUCTURED_FIELDS = (
    "title",
    "location",
    "department",
    "employment_type",
    "required_experience",
    "required_education",
    "industry",
    "function",
)


@dataclass(frozen=True, slots=True)
class FraudModelReport:
    records: int
    fraudulent: int
    train_records: int
    validation_records: int
    test_records: int
    threshold: float
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    unmitigated_fer_at_k: float
    model_adjusted_fer_at_k: float
    model_sha256: str


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _text(row: dict[str, str], key: str) -> str:
    return " ".join((row.get(key) or "").split())


def _flag(row: dict[str, str], key: str, present: str, absent: str) -> str:
    return present if str(row.get(key) or "0").strip() == "1" else absent


def row_text(row: dict[str, str]) -> str:
    salary = _text(row, "salary_range") or "MISSING_SALARY"
    verification_markers = _text(row, "verification_evidence_markers")
    verification_risk = _text(row, "verification_risk_score")
    parts = [
        "metadata: "
        + " | ".join((
            _flag(row, "has_company_logo", "HAS_LOGO", "MISSING_LOGO"),
            _flag(row, "has_questions", "HAS_SCREENING_QUESTIONS", "NO_SCREENING_QUESTIONS"),
            _flag(row, "telecommuting", "REMOTE_ALLOWED", "ONSITE_OR_UNSPECIFIED"),
            f"salary: {salary}",
            f"verification: {verification_markers}" if verification_markers else "NO_EXTERNAL_VERIFICATION",
            f"verification_risk: {verification_risk}" if verification_risk else "NO_VERIFICATION_RISK",
        )),
    ]
    for key in STRUCTURED_FIELDS:
        value = _text(row, key)
        if value:
            parts.append(f"{key}: {value}")
    for key in TEXT_FIELDS:
        value = _text(row, key)
        if value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    required = set(TEXT_FIELDS) | {"fraudulent"}
    missing = required - set(rows[0] if rows else {})
    if missing:
        raise ValueError(f"missing EMSCAD columns: {', '.join(sorted(missing))}")
    if not rows:
        raise ValueError("EMSCAD CSV is empty")
    return rows


def _label(row: dict[str, str]) -> int:
    return int(float(row.get("fraudulent") or "0"))


def _stable_id(row: dict[str, str], index: int) -> str:
    raw = row.get("job_id") or json.dumps(row, sort_keys=True)
    return hashlib.sha256(f"{index}:{raw}".encode("utf-8")).hexdigest()


def _best_threshold(scores: list[float], labels: list[int]) -> float:
    best_threshold = 0.5
    best_score = -1.0
    for threshold in sorted({0.5, *(round(score, 4) for score in scores)}):
        predictions = [score >= threshold for score in scores]
        precision, recall, f1, _ = precision_recall_fscore_support(
            labels,
            predictions,
            average="binary",
            zero_division=0,
        )
        score = float(f1)
        if score > best_score or (math.isclose(score, best_score) and threshold < best_threshold):
            best_score = score
            best_threshold = threshold
    return best_threshold


def evaluate(rows: list[dict[str, str]], top_k: int, risk_penalty: float) -> FraudModelReport:
    indexed = list(enumerate(rows))
    labels = [_label(row) for _, row in indexed]
    train_plus_validation, test = train_test_split(
        indexed,
        test_size=0.2,
        random_state=1500,
        stratify=labels,
    )
    train_validation_labels = [_label(row) for _, row in train_plus_validation]
    train, validation = train_test_split(
        train_plus_validation,
        test_size=0.125,
        random_state=1500,
        stratify=train_validation_labels,
    )
    model = Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=100_000, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=80_000, sublinear_tf=True)),
        ])),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=2000, n_jobs=1, random_state=1500)),
    ])
    model.fit([row_text(row) for _, row in train], [_label(row) for _, row in train])
    validation_scores = [float(score) for score in model.predict_proba([row_text(row) for _, row in validation])[:, 1]]
    threshold = _best_threshold(validation_scores, [_label(row) for _, row in validation])
    test_scores = [float(score) for score in model.predict_proba([row_text(row) for _, row in test])[:, 1]]
    test_labels = [_label(row) for _, row in test]
    predictions = [score >= threshold for score in test_scores]
    tn, fp, fn, tp = confusion_matrix(test_labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(
        test_labels,
        predictions,
        average="binary",
        zero_division=0,
    )
    scored = []
    for (index, row), score in zip(test, test_scores, strict=True):
        exported = map_row(row)
        scored.append({
            "id": _stable_id(row, index),
            "fraudulent": bool(_label(row)),
            "model_score": score,
            "source_relevance_score": float(exported["source_relevance_score"]),
        })
    unmitigated = sorted(scored, key=lambda item: item["source_relevance_score"], reverse=True)[:top_k]
    adjusted = sorted(
        scored,
        key=lambda item: item["source_relevance_score"] - risk_penalty * item["model_score"],
        reverse=True,
    )[:top_k]
    manifest = {
        "format": "valence-emscad-tfidf-logistic-v1",
        "records": len(rows),
        "fraudulent": sum(labels),
        "threshold": threshold,
        "features": int(model.named_steps["features"].transformer_list[0][1].idf_.shape[0])
        + int(model.named_steps["features"].transformer_list[1][1].idf_.shape[0]),
    }
    return FraudModelReport(
        records=len(rows),
        fraudulent=sum(labels),
        train_records=len(train),
        validation_records=len(validation),
        test_records=len(test),
        threshold=threshold,
        true_positive=int(tp),
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        accuracy=_ratio(tp + tn, len(test_labels)),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        false_positive_rate=_ratio(fp, fp + tn),
        unmitigated_fer_at_k=_ratio(sum(item["fraudulent"] for item in unmitigated), len(unmitigated)),
        model_adjusted_fer_at_k=_ratio(sum(item["fraudulent"] for item in adjusted), len(adjusted)),
        model_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate a deterministic EMSCAD fraud baseline")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=50)
    parser.add_argument("--risk-penalty", type=float, default=0.8)
    args = parser.parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    report = evaluate(load_rows(args.input), args.top_k, args.risk_penalty)
    payload = asdict(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
