from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
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
    split_strategy: str
    campaign_groups: int
    train_test_group_overlap: int
    regularization_c: float
    false_positive_cost: float
    minimum_recall: float
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
    combined_text = " ".join(_text(row, key) for key in TEXT_FIELDS)
    word_count = len(combined_text.split())
    link_count = len(re.findall(r"https?://|www\.", combined_text, flags=re.IGNORECASE))
    email_count = len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", combined_text))
    urgency_count = len(re.findall(r"\b(?:urgent|immediately|limited time|start today|act now)\b", combined_text, flags=re.IGNORECASE))
    finance_count = len(re.findall(r"\b(?:wire|crypto|bitcoin|processing fee|upfront|bank account|western union)\b", combined_text, flags=re.IGNORECASE))
    profile_words = len(_text(row, "company_profile").split())
    parts = [
        "metadata: "
        + " | ".join((
            _flag(row, "has_company_logo", "HAS_LOGO", "MISSING_LOGO"),
            _flag(row, "has_questions", "HAS_SCREENING_QUESTIONS", "NO_SCREENING_QUESTIONS"),
            _flag(row, "telecommuting", "REMOTE_ALLOWED", "ONSITE_OR_UNSPECIFIED"),
            f"salary: {salary}",
            f"verification: {verification_markers}" if verification_markers else "NO_EXTERNAL_VERIFICATION",
            f"verification_risk: {verification_risk}" if verification_risk else "NO_VERIFICATION_RISK",
            f"TEXT_LENGTH_{min(word_count // 100, 20)}",
            f"LINK_COUNT_{min(link_count, 5)}",
            f"EMAIL_COUNT_{min(email_count, 5)}",
            f"URGENCY_COUNT_{min(urgency_count, 5)}",
            f"FINANCE_RISK_COUNT_{min(finance_count, 5)}",
            "SPARSE_COMPANY_PROFILE" if profile_words < 20 else "SUBSTANTIVE_COMPANY_PROFILE",
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


def _campaign_group(row: dict[str, str], index: int) -> str:
    for key in ("verification_posting_domain", "verification_company_domain", "company_domain"):
        value = _text(row, key).casefold()
        if value:
            return f"domain:{value}"
    profile = _text(row, "company_profile").casefold()
    if profile:
        return "profile:" + hashlib.sha256(profile.encode("utf-8")).hexdigest()
    fallback = "\x1f".join((
        _text(row, "title").casefold(),
        _text(row, "location").casefold(),
        _text(row, "department").casefold(),
        _text(row, "description").casefold()[:512],
    ))
    if fallback.strip("\x1f"):
        return "content:" + hashlib.sha256(fallback.encode("utf-8")).hexdigest()
    return f"record:{index}"


def _split_rows(
    indexed: list[tuple[int, dict[str, str]]],
    split_strategy: str,
) -> tuple[list[tuple[int, dict[str, str]]], list[tuple[int, dict[str, str]]], list[tuple[int, dict[str, str]]]]:
    labels = [_label(row) for _, row in indexed]
    if split_strategy == "random":
        train_plus_validation, test = train_test_split(
            indexed, test_size=0.2, random_state=1500, stratify=labels,
        )
        train, validation = train_test_split(
            train_plus_validation,
            test_size=0.125,
            random_state=1500,
            stratify=[_label(row) for _, row in train_plus_validation],
        )
        return train, validation, test
    if split_strategy != "group":
        raise ValueError("split_strategy must be random or group")
    groups = [_campaign_group(row, index) for index, row in indexed]
    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=1500)
    train_validation_indices, test_indices = next(outer.split(indexed, labels, groups))
    train_plus_validation = [indexed[index] for index in train_validation_indices]
    test = [indexed[index] for index in test_indices]
    inner_labels = [_label(row) for _, row in train_plus_validation]
    inner_groups = [_campaign_group(row, index) for index, row in train_plus_validation]
    inner = StratifiedGroupKFold(n_splits=8, shuffle=True, random_state=1500)
    train_indices, validation_indices = next(inner.split(train_plus_validation, inner_labels, inner_groups))
    train = [train_plus_validation[index] for index in train_indices]
    validation = [train_plus_validation[index] for index in validation_indices]
    return train, validation, test


def _best_threshold(scores: list[float], labels: list[int], minimum_recall: float = 0.0) -> float:
    best_threshold = 0.5
    best_score: tuple[float, float, float] = (-1.0, -1.0, -1.0)
    for threshold in sorted({0.5, *(round(score, 4) for score in scores)}):
        predictions = [score >= threshold for score in scores]
        precision, recall, f1, _ = precision_recall_fscore_support(
            labels,
            predictions,
            average="binary",
            zero_division=0,
        )
        if minimum_recall > 0:
            score = (float(precision), float(f1), -threshold) if recall >= minimum_recall else (-1.0, float(f1), -threshold)
        else:
            score = (float(f1), float(precision), -threshold)
        if score > best_score:
            best_score = score
            best_threshold = threshold
    return best_threshold


def evaluate(
    rows: list[dict[str, str]],
    top_k: int,
    risk_penalty: float,
    split_strategy: str = "random",
    regularization_c: float = 1.0,
    false_positive_cost: float = 1.0,
    minimum_recall: float = 0.0,
) -> FraudModelReport:
    indexed = list(enumerate(rows))
    labels = [_label(row) for _, row in indexed]
    train, validation, test = _split_rows(indexed, split_strategy)
    all_groups = {_campaign_group(row, index) for index, row in indexed}
    train_groups = {_campaign_group(row, index) for index, row in train}
    test_groups = {_campaign_group(row, index) for index, row in test}
    train_labels = [_label(row) for _, row in train]
    negative = train_labels.count(0)
    positive = train_labels.count(1)
    class_weight = {
        0: false_positive_cost * len(train_labels) / (2 * negative),
        1: len(train_labels) / (2 * positive),
    }
    model = Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=100_000, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=80_000, sublinear_tf=True)),
        ])),
        ("classifier", LogisticRegression(class_weight=class_weight, C=regularization_c, max_iter=2000, n_jobs=1, random_state=1500)),
    ])
    model.fit([row_text(row) for _, row in train], train_labels)
    validation_scores = [float(score) for score in model.predict_proba([row_text(row) for _, row in validation])[:, 1]]
    threshold = _best_threshold(validation_scores, [_label(row) for _, row in validation], minimum_recall)
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
        "split_strategy": split_strategy,
        "regularization_c": regularization_c,
        "false_positive_cost": false_positive_cost,
        "minimum_recall": minimum_recall,
        "features": int(model.named_steps["features"].transformer_list[0][1].idf_.shape[0])
        + int(model.named_steps["features"].transformer_list[1][1].idf_.shape[0]),
    }
    return FraudModelReport(
        split_strategy=split_strategy,
        campaign_groups=len(all_groups),
        train_test_group_overlap=len(train_groups & test_groups),
        regularization_c=regularization_c,
        false_positive_cost=false_positive_cost,
        minimum_recall=minimum_recall,
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
    parser.add_argument("--split-strategy", choices=("random", "group"), default="random")
    parser.add_argument("--regularization-c", type=float, default=1.0)
    parser.add_argument("--false-positive-cost", type=float, default=1.0)
    parser.add_argument("--minimum-recall", type=float, default=0.0)
    args = parser.parse_args()
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    if args.regularization_c <= 0:
        raise ValueError("--regularization-c must be positive")
    if args.false_positive_cost <= 0:
        raise ValueError("--false-positive-cost must be positive")
    if not 0 <= args.minimum_recall <= 1:
        raise ValueError("--minimum-recall must be between 0 and 1")
    report = evaluate(
        load_rows(args.input), args.top_k, args.risk_penalty, args.split_strategy,
        args.regularization_c, args.false_positive_cost, args.minimum_recall,
    )
    payload = asdict(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
