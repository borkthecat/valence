from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from train_emscad_fraud_model import _label, row_text


URL_OR_EMAIL = re.compile(r"(?:https?://\S+|[\w.+-]+@[\w.-]+)", re.IGNORECASE)
NUMBER = re.compile(r"\d+")
WHITESPACE = re.compile(r"\s+")


def structural_signature(row: dict[str, str]) -> str:
    text = "\n".join(row.get(key, "") or "" for key in ("title", "company_profile", "description", "requirements", "benefits"))[:6_000]
    normalized = NUMBER.sub("#", URL_OR_EMAIL.sub("<CONTACT>", text.casefold()))
    tokens = WHITESPACE.sub(" ", normalized).split()
    punctuation = "".join(character for character in normalized if not character.isalnum() and not character.isspace())
    return " ".join((
        "layout:" + "_".join(str(min(12, len(part) // 80)) for part in normalized.split("\n")),
        "tokens:" + "_".join(token if len(token) < 16 else "<LONG>" for token in tokens[:500]),
        f"punct:{punctuation[:300]}",
    ))


def external_text(row: dict[str, str]) -> str:
    return " ".join((
        row.get("verification_evidence_markers", "") or "NO_EXTERNAL_EVIDENCE",
        f"risk:{row.get('verification_risk_score', '') or 'unknown'}",
        f"company_live:{row.get('verification_company_domain_live', '') or 'unknown'}",
        f"posting_live:{row.get('verification_posting_url_live', '') or 'unknown'}",
    ))


def metadata_text(row: dict[str, str]) -> str:
    return row_text(row)[:4_000]


def has_external_evidence(row: dict[str, str]) -> bool:
    return bool((row.get("verification_company_domain") or "").strip() or (row.get("verification_posting_domain") or "").strip())


def _pipeline(analyzer: str = "word") -> Pipeline:
    if analyzer == "structural":
        features: Any = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 6), min_df=3, max_features=8_000, sublinear_tf=True)
    elif analyzer == "external":
        features = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=2_000, sublinear_tf=True)
    else:
        features = FeatureUnion([
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=8_000, sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, max_features=8_000, sublinear_tf=True)),
        ])
    return Pipeline([("features", features), ("classifier", LogisticRegression(class_weight="balanced", max_iter=2000, n_jobs=1, random_state=1500))])


def _threshold_at_recall(scores: list[float], labels: list[int], target: float) -> float:
    candidates = sorted({0.0, *(round(score, 6) for score in scores)})
    valid = []
    for threshold in candidates:
        predictions = [score >= threshold for score in scores]
        precision, recall, _, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
        if recall >= target:
            valid.append((float(precision), threshold))
    return max(valid)[1] if valid else 0.0


def _best_f1_threshold(scores: list[float], labels: list[int]) -> float:
    best = (0.0, 0.5)
    for threshold in sorted({0.0, *(round(score, 6) for score in scores)}):
        _, _, f1, _ = precision_recall_fscore_support(labels, [score >= threshold for score in scores], average="binary", zero_division=0)
        best = max(best, (float(f1), threshold))
    return best[1]


def _metrics(labels: list[int], predictions: list[bool]) -> dict[str, float | int]:
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    return {"truePositive": int(tp), "trueNegative": int(tn), "falsePositive": int(fp), "falseNegative": int(fn), "accuracy": (tp + tn) / len(labels), "precision": float(precision), "recall": float(recall), "f1": float(f1), "falsePositiveRate": fp / (fp + tn) if fp + tn else 0.0}


def evaluate(rows: list[dict[str, str]], *, sieve_recall: float, audit_size: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    indexed = list(enumerate(rows))
    labels = [_label(row) for _, row in indexed]
    train_validation, test = train_test_split(indexed, test_size=0.2, random_state=1500, stratify=labels)
    train, validation = train_test_split(train_validation, test_size=0.125, random_state=1500, stratify=[_label(row) for _, row in train_validation])
    base_model, external_model, verifier = _pipeline(), _pipeline("external"), _pipeline("structural")
    base_model.fit([metadata_text(row) for _, row in train], [_label(row) for _, row in train])
    external_model.fit([external_text(row) for _, row in train], [_label(row) for _, row in train])
    validation_base = base_model.predict_proba([metadata_text(row) for _, row in validation])[:, 1]
    validation_external = external_model.predict_proba([external_text(row) for _, row in validation])[:, 1]
    validation_fused = [0.6 * base + 0.4 * external if has_external_evidence(row) else base for (_, row), base, external in zip(validation, validation_base, validation_external, strict=True)]
    sieve_threshold = _threshold_at_recall([float(value) for value in validation_fused], [_label(row) for _, row in validation], sieve_recall)
    candidate_train = [(row, score) for (_, row), score in zip(train, base_model.predict_proba([metadata_text(row) for _, row in train])[:, 1], strict=True) if score >= sieve_threshold]
    if len({_label(row) for row, _ in candidate_train}) < 2:
        candidate_train = [(row, 0.0) for _, row in train]
    verifier.fit([structural_signature(row) for row, _ in candidate_train], [_label(row) for row, _ in candidate_train])
    validation_verifier = verifier.predict_proba([structural_signature(row) for _, row in validation])[:, 1]
    verifier_threshold = _best_f1_threshold([float(value) for value in validation_verifier], [_label(row) for _, row in validation])
    base_scores = base_model.predict_proba([metadata_text(row) for _, row in test])[:, 1]
    external_scores = external_model.predict_proba([external_text(row) for _, row in test])[:, 1]
    fused_scores = [0.6 * base + 0.4 * external if has_external_evidence(row) else base for (_, row), base, external in zip(test, base_scores, external_scores, strict=True)]
    verifier_scores = verifier.predict_proba([structural_signature(row) for _, row in test])[:, 1]
    predictions = [fused >= sieve_threshold and verify >= verifier_threshold for fused, verify in zip(fused_scores, verifier_scores, strict=True)]
    audits = []
    for (index, row), base, external, fused, verify in zip(test, base_scores, external_scores, fused_scores, verifier_scores, strict=True):
        audits.append({"record_id": str(row.get("job_id") or index), "tfidf_confidence": float(base), "external_confidence": float(external), "fused_confidence": float(fused), "verifier_confidence": float(verify), "disagreement_delta": abs(float(fused) - float(verify)), "external_evidence_present": has_external_evidence(row), "audit_status": "PENDING_REVIEW"})
    audits.sort(key=lambda row: (-float(row["disagreement_delta"]), row["record_id"]))
    report = {"records": len(rows), "trainRecords": len(train), "validationRecords": len(validation), "testRecords": len(test), "sieveRecallTarget": sieve_recall, "sieveThreshold": sieve_threshold, "verifierThreshold": verifier_threshold, "externalEvidenceTestRecords": sum(has_external_evidence(row) for _, row in test), "cascade": _metrics([_label(row) for _, row in test], predictions)}
    return report, audits[:audit_size]


def stratified_limit(rows: list[dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    if limit is None or limit >= len(rows):
        return rows
    groups: dict[int, list[dict[str, str]]] = {0: [], 1: []}
    for row in rows:
        groups[_label(row)].append(row)
    for group in groups.values():
        group.sort(key=lambda row: hashlib.sha256((row.get("job_id") or "").encode("utf-8")).hexdigest())
    positive_count = max(1, round(limit * len(groups[1]) / len(rows)))
    return [*groups[0][:limit - positive_count], *groups[1][:positive_count]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a recall-first fraud cascade and build a human audit queue")
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--sieve-recall", type=float, default=0.965); parser.add_argument("--audit-size", type=int, default=200); parser.add_argument("--max-records", type=int)
    args = parser.parse_args()
    if not 0 < args.sieve_recall <= 1 or args.audit_size <= 0: raise ValueError("invalid cascade limits")
    with args.input.open("r", encoding="utf-8-sig", newline="") as source: rows = stratified_limit(list(csv.DictReader(source)), args.max_records)
    report, audits = evaluate(rows, sieve_recall=args.sieve_recall, audit_size=args.audit_size)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    with args.audit_output.open("w", encoding="utf-8", newline="\n") as target:
        for audit in audits: target.write(json.dumps(audit, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"report": str(args.output), "auditRecords": len(audits), **report["cascade"]}, sort_keys=True))


if __name__ == "__main__": raise SystemExit(main())
