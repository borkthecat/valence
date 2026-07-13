from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

try:
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except ImportError:  # Transformer benchmarks are optional for core development.
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = Any  # type: ignore[misc,assignment]
    Dataset = object  # type: ignore[misc,assignment]
    WeightedRandomSampler = None  # type: ignore[assignment]
    AutoModelForSequenceClassification = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]

from train_emscad_fraud_model import load_rows, row_text


def require_transformer_dependencies() -> None:
    if torch is None or AutoTokenizer is None or AutoModelForSequenceClassification is None:
        raise RuntimeError(
            "This command requires transformer dependencies. Install them with: "
            "pip install -r requirements-transformer.txt"
        )


@dataclass(frozen=True, slots=True)
class TransformerFraudReport:
    base_model: str
    records: int
    fraudulent: int
    train_records: int
    validation_records: int
    test_records: int
    threshold: float
    positive_class_weight: float
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    model_sha256: str


class FraudDataset(Dataset):
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, str]:
        return self.rows[index]


def label_of(row: dict[str, str]) -> int:
    return int(float(row.get("fraudulent") or "0"))


def _flag(row: dict[str, str], key: str, present: str, absent: str) -> str:
    return present if str(row.get(key) or "0").strip() == "1" else absent


def enriched_row_text(row: dict[str, str]) -> str:
    metadata = [
        _flag(row, "has_company_logo", "HAS_LOGO", "MISSING_LOGO"),
        _flag(row, "has_questions", "HAS_SCREENING_QUESTIONS", "NO_SCREENING_QUESTIONS"),
        _flag(row, "telecommuting", "REMOTE_ALLOWED", "ONSITE_OR_UNSPECIFIED"),
    ]
    salary = " ".join((row.get("salary_range") or "").split()) or "MISSING_SALARY"
    department = " ".join((row.get("department") or "").split()) or "MISSING_DEPARTMENT"
    return "\n".join((
        f"metadata: {' | '.join(metadata)} | salary: {salary} | department: {department}",
        row_text(row),
    ))


def split_rows(
    rows: list[dict[str, str]],
    seed: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    labels = [label_of(row) for row in rows]
    train_validation, test = train_test_split(rows, test_size=0.2, random_state=seed, stratify=labels)
    train_validation_labels = [label_of(row) for row in train_validation]
    train, validation = train_test_split(
        train_validation,
        test_size=0.125,
        random_state=seed,
        stratify=train_validation_labels,
    )
    return list(train), list(validation), list(test)


def best_threshold(scores: list[float], labels: list[int]) -> float:
    best = (0.0, 0.5)
    for threshold in sorted({0.5, *(round(score, 4) for score in scores)}):
        predictions = [score >= threshold for score in scores]
        precision, recall, f1, _ = precision_recall_fscore_support(
            labels,
            predictions,
            average="binary",
            zero_division=0,
        )
        score = min(float(precision), float(recall), float(f1))
        if score > best[0] or (score == best[0] and threshold < best[1]):
            best = (score, threshold)
    return best[1]


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def _load_tokenizer(model_name: str) -> Any:
    try:
        return AutoTokenizer.from_pretrained(model_name)
    except AttributeError:
        return AutoTokenizer.from_pretrained(model_name, use_fast=False)


def _report(
    base_model: str,
    train: list[dict[str, str]],
    validation: list[dict[str, str]],
    test: list[dict[str, str]],
    threshold: float,
    positive_class_weight: float,
    scores: list[float],
) -> TransformerFraudReport:
    labels = [label_of(row) for row in test]
    predictions = [score >= threshold for score in scores]
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    manifest = {
        "format": "valence-emscad-transformer-fraud-v1",
        "baseModel": base_model,
        "records": len(train) + len(validation) + len(test),
        "threshold": threshold,
        "positiveClassWeight": positive_class_weight,
    }
    return TransformerFraudReport(
        base_model=base_model,
        records=len(train) + len(validation) + len(test),
        fraudulent=sum(label_of(row) for row in [*train, *validation, *test]),
        train_records=len(train),
        validation_records=len(validation),
        test_records=len(test),
        threshold=threshold,
        positive_class_weight=positive_class_weight,
        true_positive=int(tp),
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        accuracy=_ratio(tp + tn, len(labels)),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        false_positive_rate=_ratio(fp, fp + tn),
        model_sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest(),
    )


def train(args: argparse.Namespace) -> TransformerFraudReport:
    rows = load_rows(args.input)
    if args.limit:
        rows = rows[: args.limit]
    train_rows, validation_rows, test_rows = split_rows(rows, args.seed)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available() and not args.cpu:
        device = torch.device("cuda")
        torch.cuda.manual_seed_all(args.seed)
    else:
        device = torch.device("cpu")
    tokenizer = _load_tokenizer(args.base_model)
    model = AutoModelForSequenceClassification.from_pretrained(args.base_model, num_labels=2)
    model.to(device)
    negative_train = sum(label_of(row) == 0 for row in train_rows)
    positive_train = sum(label_of(row) == 1 for row in train_rows)
    positive_class_weight = args.fraud_loss_weight or (negative_train / max(1, positive_train))
    class_weights = torch.tensor([1.0, positive_class_weight], dtype=torch.float32, device=device)
    loss_function = nn.CrossEntropyLoss(weight=class_weights)

    def collate(batch: list[dict[str, str]]) -> tuple[dict[str, torch.Tensor], torch.Tensor]:
        encoded = tokenizer(
            [enriched_row_text(row) for row in batch],
            padding=True,
            truncation=True,
            max_length=args.max_length,
            return_tensors="pt",
        )
        labels = torch.tensor([label_of(row) for row in batch], dtype=torch.long)
        return encoded, labels

    groups = {label: max(1, sum(label_of(row) == label for row in train_rows)) for label in (0, 1)}
    weights = [1.0 / groups[label_of(row)] for row in train_rows]
    sampler = WeightedRandomSampler(weights, len(train_rows), replacement=True, generator=torch.Generator().manual_seed(args.seed))
    train_loader = DataLoader(FraudDataset(train_rows), batch_size=args.batch_size, sampler=sampler, collate_fn=collate)
    validation_loader = DataLoader(FraudDataset(validation_rows), batch_size=args.batch_size * 4, shuffle=False, collate_fn=collate)
    test_loader = DataLoader(FraudDataset(test_rows), batch_size=args.batch_size * 4, shuffle=False, collate_fn=collate)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.01)

    for epoch in range(args.epochs):
        model.train()
        for batch, labels in train_loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(**batch).logits
            loss = loss_function(logits, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        print(json.dumps({"epoch": epoch + 1, "loss": float(loss.detach().cpu())}), flush=True)

    validation_scores = _scores(model, validation_loader, device)
    threshold = best_threshold(validation_scores, [label_of(row) for row in validation_rows])
    test_scores = _scores(model, test_loader, device)
    if args.model_output:
        args.model_output.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(args.model_output, safe_serialization=True)
        tokenizer.save_pretrained(args.model_output)
    return _report(args.base_model, train_rows, validation_rows, test_rows, threshold, positive_class_weight, test_scores)


def _scores(model: Any, loader: DataLoader, device: torch.device) -> list[float]:
    scores: list[float] = []
    model.eval()
    with torch.inference_mode():
        for batch, _ in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            logits = model(**batch).logits
            scores.extend(torch.softmax(logits, dim=-1)[:, 1].detach().cpu().tolist())
    return [float(score) for score in scores]


def main() -> int:
    require_transformer_dependencies()
    parser = argparse.ArgumentParser(description="Train a transformer EMSCAD fake-job fraud classifier")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--base-model", default="microsoft/deberta-v3-small")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--fraud-loss-weight", type=float)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--seed", type=int, default=1500)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    if args.epochs <= 0 or args.batch_size <= 0:
        raise ValueError("epochs and batch size must be positive")
    report = train(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
