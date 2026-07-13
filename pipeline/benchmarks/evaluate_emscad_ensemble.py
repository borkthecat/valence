from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

try:
    from .analyze_emscad_false_negatives import split_indexed_rows, train_tfidf_model
    from .train_emscad_fraud_model import _best_threshold, _label, load_rows, row_text
    from .train_emscad_transformer_fraud import FraudDataset, enriched_row_text
except ImportError:
    from analyze_emscad_false_negatives import split_indexed_rows, train_tfidf_model
    from train_emscad_fraud_model import _best_threshold, _label, load_rows, row_text
    from train_emscad_transformer_fraud import FraudDataset, enriched_row_text


@dataclass(frozen=True, slots=True)
class StrategyReport:
    strategy: str
    threshold: float
    weight: float | None
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _metrics(strategy: str, labels: list[int], scores: list[float], threshold: float, weight: float | None = None) -> StrategyReport:
    predictions = [score >= threshold for score in scores]
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    return StrategyReport(
        strategy=strategy,
        threshold=threshold,
        weight=weight,
        true_positive=int(tp),
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        accuracy=_ratio(tp + tn, len(labels)),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        false_positive_rate=_ratio(fp, fp + tn),
    )


def _best_f1_threshold(scores: list[float], labels: list[int]) -> float:
    best_threshold = 0.5
    best_score = -1.0
    for threshold in sorted({0.5, *(round(score, 4) for score in scores)}):
        _, _, f1, _ = precision_recall_fscore_support(labels, [score >= threshold for score in scores], average="binary", zero_division=0)
        if float(f1) > best_score or (math.isclose(float(f1), best_score) and threshold < best_threshold):
            best_score = float(f1)
            best_threshold = threshold
    return best_threshold


def _best_threshold_under_fpr(scores: list[float], labels: list[int], max_fpr: float) -> float | None:
    best_threshold: float | None = None
    best_score = -1.0
    for threshold in sorted({0.5, *(round(score, 4) for score in scores)}):
        predictions = [score >= threshold for score in scores]
        tn, fp, _, _ = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
        fpr = _ratio(fp, fp + tn)
        if fpr > max_fpr:
            continue
        _, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
        score = float(f1)
        if score > best_score or (
            math.isclose(score, best_score)
            and best_threshold is not None
            and float(recall) > precision_recall_fscore_support(labels, [value >= best_threshold for value in scores], average="binary", zero_division=0)[1]
        ):
            best_score = score
            best_threshold = threshold
    return best_threshold


def _load_tokenizer(model_path: Path) -> Any:
    try:
        return AutoTokenizer.from_pretrained(model_path)
    except AttributeError:
        return AutoTokenizer.from_pretrained(model_path, use_fast=False)


def _transformer_scores(model_path: Path, rows: list[dict[str, str]], batch_size: int, max_length: int, cpu: bool) -> list[float]:
    if not model_path.exists():
        raise FileNotFoundError(
            f"transformer model path does not exist: {model_path}. "
            "Run train_emscad_transformer_fraud.py with --model-output first, then rerun this ensemble evaluator."
        )
    device = torch.device("cuda" if torch.cuda.is_available() and not cpu else "cpu")
    tokenizer = _load_tokenizer(model_path)
    model = AutoModelForSequenceClassification.from_pretrained(model_path)
    model.to(device)
    model.eval()

    def collate(batch: list[dict[str, str]]) -> dict[str, torch.Tensor]:
        return tokenizer(
            [enriched_row_text(row) for row in batch],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )

    scores: list[float] = []
    loader = DataLoader(FraudDataset(rows), batch_size=batch_size, shuffle=False, collate_fn=collate)
    with torch.inference_mode():
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits
            scores.extend(torch.softmax(logits, dim=-1)[:, 1].detach().cpu().tolist())
    return [float(score) for score in scores]


def evaluate(rows: list[dict[str, str]], transformer_model: Path, batch_size: int, max_length: int, cpu: bool, max_fpr: float) -> dict[str, Any]:
    train, validation, test = split_indexed_rows(rows)
    tfidf_model = train_tfidf_model(train)
    validation_labels = [_label(row) for _, row in validation]
    test_labels = [_label(row) for _, row in test]
    validation_tfidf = [float(score) for score in tfidf_model.predict_proba([row_text(row) for _, row in validation])[:, 1]]
    test_tfidf = [float(score) for score in tfidf_model.predict_proba([row_text(row) for _, row in test])[:, 1]]
    validation_transformer = _transformer_scores(transformer_model, [row for _, row in validation], batch_size, max_length, cpu)
    test_transformer = _transformer_scores(transformer_model, [row for _, row in test], batch_size, max_length, cpu)

    reports: list[StrategyReport] = []
    reports.append(_metrics("tfidf", test_labels, test_tfidf, _best_threshold(validation_tfidf, validation_labels)))
    reports.append(_metrics("transformer", test_labels, test_transformer, _best_f1_threshold(validation_transformer, validation_labels)))
    validation_max = [max(left, right) for left, right in zip(validation_tfidf, validation_transformer, strict=True)]
    test_max = [max(left, right) for left, right in zip(test_tfidf, test_transformer, strict=True)]
    reports.append(_metrics("max_score", test_labels, test_max, _best_f1_threshold(validation_max, validation_labels)))

    best_weight: tuple[float, float, list[float], list[float]] | None = None
    for step in range(0, 21):
        weight = step / 20
        validation_scores = [(weight * left) + ((1 - weight) * right) for left, right in zip(validation_tfidf, validation_transformer, strict=True)]
        threshold = _best_f1_threshold(validation_scores, validation_labels)
        predictions = [score >= threshold for score in validation_scores]
        _, _, f1, _ = precision_recall_fscore_support(validation_labels, predictions, average="binary", zero_division=0)
        test_scores = [(weight * left) + ((1 - weight) * right) for left, right in zip(test_tfidf, test_transformer, strict=True)]
        candidate = (float(f1), weight, validation_scores, test_scores)
        if best_weight is None or candidate[0] > best_weight[0]:
            best_weight = candidate
    assert best_weight is not None
    _, weight, validation_weighted, test_weighted = best_weight
    reports.append(_metrics("weighted_score", test_labels, test_weighted, _best_f1_threshold(validation_weighted, validation_labels), weight=weight))
    constrained_reports: list[StrategyReport] = []
    for step in range(0, 21):
        constrained_weight = step / 20
        validation_scores = [
            (constrained_weight * left) + ((1 - constrained_weight) * right)
            for left, right in zip(validation_tfidf, validation_transformer, strict=True)
        ]
        threshold = _best_threshold_under_fpr(validation_scores, validation_labels, max_fpr)
        if threshold is None:
            continue
        test_scores = [
            (constrained_weight * left) + ((1 - constrained_weight) * right)
            for left, right in zip(test_tfidf, test_transformer, strict=True)
        ]
        constrained_reports.append(_metrics("weighted_score_fpr_constrained", test_labels, test_scores, threshold, weight=constrained_weight))
    if constrained_reports:
        constrained_reports.sort(key=lambda report: (-report.f1, -report.recall, report.false_positive_rate, report.strategy))
        reports.append(constrained_reports[0])

    tfidf_threshold = _best_threshold(validation_tfidf, validation_labels)
    transformer_threshold = _best_f1_threshold(validation_transformer, validation_labels)
    or_scores = [
        1.0 if left >= tfidf_threshold or right >= transformer_threshold else 0.0
        for left, right in zip(test_tfidf, test_transformer, strict=True)
    ]
    reports.append(_metrics("threshold_or", test_labels, or_scores, 0.5, weight=None))

    reports.sort(key=lambda report: (-report.f1, -report.recall, report.false_positive_rate, report.strategy))
    return {
        "records": len(rows),
        "train_records": len(train),
        "validation_records": len(validation),
        "test_records": len(test),
        "transformer_model": str(transformer_model),
        "validation_max_fpr": max_fpr,
        "strategies": [asdict(report) for report in reports],
        "best_strategy": asdict(reports[0]),
        "best_fpr_constrained_strategy": None if not constrained_reports else asdict(constrained_reports[0]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate EMSCAD TF-IDF plus transformer ensemble strategies on the deterministic held-out split")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--transformer-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--max-fpr", type=float, default=0.003526300323244196)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    if args.batch_size <= 0 or args.max_length <= 0 or not 0 <= args.max_fpr <= 1:
        raise ValueError("batch size, max length, and max FPR must be valid")
    report = evaluate(load_rows(args.input), args.transformer_model, args.batch_size, args.max_length, args.cpu, args.max_fpr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["best_strategy"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
