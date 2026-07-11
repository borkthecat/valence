from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TARGETS = frozenset({"hse_llm", "cgoosen_combined", "cgoosen_guard", "jcanode", "smooth_3"})
ARTIFACT_LINES = re.compile(r"(?im)^\s*(?:source[_ -]?id|author|created(?:_at)?|date|timestamp|filename|file[_ -]?path)\s*[:=].*$")
VALENCE_TAGS = re.compile(r"(?i)</?(?:valence_source|valence_article|user_session)\b[^>]*>")
SPACE = re.compile(r"\s+")


def sanitize_text(text: str) -> str:
    return SPACE.sub(" ", VALENCE_TAGS.sub("", ARTIFACT_LINES.sub("", text))).strip()


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()


def audit(records: list[dict[str, Any]], *, minimum_per_label: int, negatives_only: bool = False, allow_rejected: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: dict[tuple[str, str], bool] = {}
    groups: dict[str, dict[bool, list[dict[str, Any]]]] = defaultdict(lambda: {False: [], True: []})
    for index, record in enumerate(records, 1):
        source, label, text = record.get("source"), record.get("label"), record.get("text")
        if source not in TARGETS or not isinstance(label, bool) or not isinstance(text, str):
            errors.append(f"line {index}: requires target source, boolean label, and text")
            continue
        cleaned = sanitize_text(text)
        if len(cleaned) < 24:
            errors.append(f"line {index}: sanitized text is too short")
            continue
        digest = fingerprint(cleaned)
        key = (source, digest)
        prior = seen.get(key)
        if prior is not None:
            errors.append(f"line {index}: duplicate text or cross-label collision")
            continue
        seen[key] = label
        row = {"source": source, "label": label, "text": cleaned, "record_id": str(record.get("record_id") or digest)}
        if isinstance(record.get("provenance"), dict):
            row["provenance"] = record["provenance"]
        sanitized.append(row); groups[source][label].append(row)
    summary: dict[str, Any] = {"sources": {}, "errors": errors}
    for source in sorted(TARGETS):
        negatives, positives = groups[source][False], groups[source][True]
        lengths = {"negative": [len(row["text"]) for row in negatives], "positive": [len(row["text"]) for row in positives]}
        median_negative = statistics.median(lengths["negative"]) if lengths["negative"] else 0
        median_positive = statistics.median(lengths["positive"]) if lengths["positive"] else 0
        ratio = max(median_negative, median_positive) / max(1, min(median_negative, median_positive))
        source_errors = []
        if len(negatives) < minimum_per_label or (not negatives_only and len(positives) < minimum_per_label):
            source_errors.append("insufficient balanced records")
        if not negatives_only and ratio > 1.5:
            source_errors.append("label-correlated text-length imbalance")
        summary["sources"][source] = {"negative": len(negatives), "positive": len(positives), "medianNegativeLength": median_negative, "medianPositiveLength": median_positive, "medianLengthRatio": ratio, "errors": source_errors}
        errors.extend(f"{source}: {error}" for error in source_errors)
    source_failures = [error for source in summary["sources"].values() for error in source["errors"]]
    summary["rejected"] = len(errors) - len(source_failures)
    summary["passed"] = not source_failures and (allow_rejected or not errors)
    return sanitized, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed audit for curated source-specific expert data")
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minimum-per-label", type=int, default=500)
    parser.add_argument("--negatives-only", action="store_true", help="audit trusted external benign records against base-corpus positives")
    parser.add_argument("--allow-rejected", action="store_true", help="retain rejected-line report while accepting a balanced sanitized subset")
    args = parser.parse_args()
    if args.minimum_per_label <= 0: raise ValueError("minimum per label must be positive")
    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    sanitized, report = audit(records, minimum_per_label=args.minimum_per_label, negatives_only=args.negatives_only, allow_rejected=args.allow_rejected)
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if report["passed"]:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as target:
            for row in sanitized: target.write(json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n")
    print(json.dumps({"passed": report["passed"], "errors": len(report["errors"]), "records": len(sanitized)})); return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
