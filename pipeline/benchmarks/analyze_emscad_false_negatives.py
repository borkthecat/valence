from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

try:
    from .train_emscad_fraud_model import _best_threshold, _label, load_rows, row_text
except ImportError:
    from train_emscad_fraud_model import _best_threshold, _label, load_rows, row_text


STRUCTURED_FIELDS = (
    "employment_type",
    "required_experience",
    "required_education",
    "industry",
    "function",
    "department",
)

TEXT_COMPLETENESS_FIELDS = (
    "company_profile",
    "description",
    "requirements",
    "benefits",
    "salary_range",
)

BINARY_FIELDS = (
    "telecommuting",
    "has_company_logo",
    "has_questions",
)


@dataclass(frozen=True, slots=True)
class SliceStats:
    field: str
    value: str
    test_records: int
    fraud_records: int
    false_negatives: int
    fraud_miss_rate: float
    share_of_false_negatives: float


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def split_indexed_rows(rows: list[dict[str, str]]) -> tuple[list[tuple[int, dict[str, str]]], list[tuple[int, dict[str, str]]], list[tuple[int, dict[str, str]]]]:
    indexed = list(enumerate(rows))
    labels = [_label(row) for _, row in indexed]
    train_validation, test = train_test_split(indexed, test_size=0.2, random_state=1500, stratify=labels)
    train_validation_labels = [_label(row) for _, row in train_validation]
    train, validation = train_test_split(
        train_validation,
        test_size=0.125,
        random_state=1500,
        stratify=train_validation_labels,
    )
    return list(train), list(validation), list(test)


def train_tfidf_model(train: list[tuple[int, dict[str, str]]]) -> Pipeline:
    model = Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=100_000, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=80_000, sublinear_tf=True)),
        ])),
        ("classifier", LogisticRegression(class_weight="balanced", max_iter=2000, n_jobs=1, random_state=1500)),
    ])
    model.fit([row_text(row) for _, row in train], [_label(row) for _, row in train])
    return model


def _bucket(row: dict[str, str], field: str) -> str:
    value = " ".join((row.get(field) or "").split())
    if field in BINARY_FIELDS:
        return "true" if value == "1" else "false"
    if not value:
        return "MISSING"
    return value[:80]


def _field_empty(row: dict[str, str], field: str) -> str:
    return "empty" if not " ".join((row.get(field) or "").split()) else "present"


def _slice_stats(
    test_rows: list[tuple[int, dict[str, str]]],
    false_negative_ids: set[int],
    field: str,
    values: list[str],
) -> list[SliceStats]:
    total_false_negatives = len(false_negative_ids)
    stats: list[SliceStats] = []
    for value in sorted(set(values)):
        matching = [(index, row) for (index, row), candidate in zip(test_rows, values, strict=True) if candidate == value]
        fraud = [(index, row) for index, row in matching if _label(row) == 1]
        false_negatives = sum(index in false_negative_ids for index, _ in fraud)
        if not fraud and not false_negatives:
            continue
        stats.append(SliceStats(
            field=field,
            value=value,
            test_records=len(matching),
            fraud_records=len(fraud),
            false_negatives=false_negatives,
            fraud_miss_rate=_ratio(false_negatives, len(fraud)),
            share_of_false_negatives=_ratio(false_negatives, total_false_negatives),
        ))
    stats.sort(key=lambda item: (-item.false_negatives, -item.fraud_miss_rate, item.field, item.value))
    return stats


def analyze(rows: list[dict[str, str]]) -> dict[str, Any]:
    train, validation, test = split_indexed_rows(rows)
    model = train_tfidf_model(train)
    validation_scores = [float(score) for score in model.predict_proba([row_text(row) for _, row in validation])[:, 1]]
    threshold = _best_threshold(validation_scores, [_label(row) for _, row in validation])
    test_scores = [float(score) for score in model.predict_proba([row_text(row) for _, row in test])[:, 1]]
    labels = [_label(row) for _, row in test]
    predictions = [score >= threshold for score in test_scores]
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    false_negative_ids = {index for (index, _), label, predicted in zip(test, labels, predictions, strict=True) if label == 1 and not predicted}

    slices: list[SliceStats] = []
    for field in STRUCTURED_FIELDS:
        slices.extend(_slice_stats(test, false_negative_ids, field, [_bucket(row, field) for _, row in test]))
    for field in TEXT_COMPLETENESS_FIELDS:
        slices.extend(_slice_stats(test, false_negative_ids, f"{field}_completeness", [_field_empty(row, field) for _, row in test]))
    for field in BINARY_FIELDS:
        slices.extend(_slice_stats(test, false_negative_ids, field, [_bucket(row, field) for _, row in test]))

    false_negatives = []
    for (index, row), score, predicted in zip(test, test_scores, predictions, strict=True):
        if _label(row) == 1 and not predicted:
            false_negatives.append({
                "row_index": index,
                "job_id": row.get("job_id") or str(index),
                "score": score,
                "threshold": threshold,
                "title": row.get("title", ""),
                "location": row.get("location", ""),
                "employment_type": row.get("employment_type", ""),
                "required_experience": row.get("required_experience", ""),
                "required_education": row.get("required_education", ""),
                "industry": row.get("industry", ""),
                "function": row.get("function", ""),
                "department": row.get("department", ""),
                "company_profile_empty": _field_empty(row, "company_profile") == "empty",
                "description_empty": _field_empty(row, "description") == "empty",
                "requirements_empty": _field_empty(row, "requirements") == "empty",
                "benefits_empty": _field_empty(row, "benefits") == "empty",
                "salary_range_empty": _field_empty(row, "salary_range") == "empty",
                "telecommuting": row.get("telecommuting", ""),
                "has_company_logo": row.get("has_company_logo", ""),
                "has_questions": row.get("has_questions", ""),
            })

    score_bands = Counter()
    for item in false_negatives:
        band_floor = int(float(item["score"]) * 10) / 10
        score_bands[f"{band_floor:.1f}-{band_floor + 0.1:.1f}"] += 1

    return {
        "records": len(rows),
        "train_records": len(train),
        "validation_records": len(validation),
        "test_records": len(test),
        "threshold": threshold,
        "metrics": {
            "true_positive": int(tp),
            "true_negative": int(tn),
            "false_positive": int(fp),
            "false_negative": int(fn),
            "accuracy": _ratio(tp + tn, len(labels)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "false_positive_rate": _ratio(fp, fp + tn),
        },
        "top_false_negative_slices": [asdict(item) for item in slices if item.false_negatives > 0][:30],
        "false_negative_score_bands": dict(sorted(score_bands.items())),
        "false_negatives": false_negatives,
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    metrics = report["metrics"]
    lines = [
        "# EMSCAD False-Negative Analysis",
        "",
        f"- Records: {report['records']}",
        f"- Test records: {report['test_records']}",
        f"- Threshold: {report['threshold']:.4f}",
        f"- False negatives: {metrics['false_negative']}",
        f"- Precision: {metrics['precision']:.4%}",
        f"- Recall: {metrics['recall']:.4%}",
        f"- F1: {metrics['f1']:.4%}",
        f"- FPR: {metrics['false_positive_rate']:.4%}",
        "",
        "## Largest False-Negative Slices",
        "",
        "| Field | Value | Test records | Fraud records | False negatives | Fraud miss rate | Share of false negatives |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in report["top_false_negative_slices"]:
        lines.append(
            f"| {item['field']} | {str(item['value']).replace('|', '/')} | {item['test_records']} | "
            f"{item['fraud_records']} | {item['false_negatives']} | {item['fraud_miss_rate']:.2%} | "
            f"{item['share_of_false_negatives']:.2%} |"
        )
    lines.extend(["", "## False-Negative Score Bands", ""])
    for band, count in report["false_negative_score_bands"].items():
        lines.append(f"- `{band}`: {count}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_false_negative_csv(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = report["false_negatives"]
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze held-out EMSCAD false negatives from the TF-IDF metadata baseline")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--false-negatives-csv", type=Path)
    args = parser.parse_args()
    report = analyze(load_rows(args.input))
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_markdown(report, args.output_md)
    if args.false_negatives_csv is not None:
        _write_false_negative_csv(report, args.false_negatives_csv)
    print(json.dumps({
        "falseNegatives": report["metrics"]["false_negative"],
        "precision": report["metrics"]["precision"],
        "recall": report["metrics"]["recall"],
        "f1": report["metrics"]["f1"],
        "falsePositiveRate": report["metrics"]["false_positive_rate"],
        "outputJson": str(args.output_json),
        "outputMarkdown": str(args.output_md),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
