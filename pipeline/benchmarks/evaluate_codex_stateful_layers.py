from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

from codex_fraud_engine import CodexFraudEngine
from train_emscad_fraud_model import _label


def mapped(row: dict[str, str]) -> dict[str, str | bool]:
    return {
        "label": bool(_label(row)),
        "posting_domain": row.get("verification_posting_domain", ""),
        "company_domain": row.get("verification_company_domain", ""),
        "description": row.get("description", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure train-only stateful fraud evidence coverage")
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-fraud-support", type=int, default=3)
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8-sig", newline="") as source: rows = list(csv.DictReader(source))
    train, test = train_test_split(rows, test_size=0.2, random_state=1500, stratify=[_label(row) for row in rows])
    engine = CodexFraudEngine(min_fraud_support=args.min_fraud_support)
    engine.train_stateful_layers([mapped(row) for row in train])
    decisions = [engine.evaluate_pipeline(mapped(row), tfidf_probability=0, verifier_probability=0) for row in test]
    labels = [_label(row) for row in test]; predictions = [decision.intercepted or "CLONE_DOMAIN_MISMATCH" in decision.evidence for decision in decisions]
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predictions, average="binary", zero_division=0)
    payload = {"records": len(rows), "testRecords": len(test), "domainBlocklistSize": len(engine.deterministic_blocklist), "cloneAlerts": sum("CLONE_DOMAIN_MISMATCH" in decision.evidence for decision in decisions), "metrics": {"truePositive": int(tp), "trueNegative": int(tn), "falsePositive": int(fp), "falseNegative": int(fn), "precision": float(precision), "recall": float(recall), "f1": float(f1)}}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main())
