from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


TEXT_FIELDS = ("company_profile", "description", "requirements", "benefits")


def _text(row: dict[str, str], key: str) -> str:
    return " ".join((row.get(key) or "").split())


def _flag(row: dict[str, str], key: str) -> int:
    try:
        return int(float(row.get(key, "0") or "0"))
    except ValueError:
        return 0


def _salary_signal(value: str) -> float:
    numbers = []
    for part in value.replace("-", " ").replace(",", "").split():
        try:
            numbers.append(float(part))
        except ValueError:
            continue
    if not numbers:
        return 0.0
    highest = max(numbers)
    return min(1.0, highest / 200_000.0)


def risk_score(row: dict[str, str]) -> float:
    score = 0.0
    score += 0.24 if not _text(row, "company_profile") else 0.0
    score += 0.18 if not _text(row, "requirements") else 0.0
    score += 0.15 if _flag(row, "has_company_logo") == 0 else 0.0
    score += 0.12 if _flag(row, "has_questions") == 0 else 0.0
    score += 0.08 if _flag(row, "telecommuting") == 1 else 0.0
    score += 0.12 * _salary_signal(row.get("salary_range", ""))
    score += 0.11 if len(" ".join(_text(row, field) for field in TEXT_FIELDS)) < 300 else 0.0
    return round(min(1.0, score), 6)


def relevance_score(row: dict[str, str]) -> float:
    text_length = len(" ".join(_text(row, field) for field in TEXT_FIELDS))
    completeness = sum(bool(_text(row, field)) for field in TEXT_FIELDS) / len(TEXT_FIELDS)
    return round(min(1.0, 0.35 + 0.45 * completeness + 0.20 * min(1.0, text_length / 2500)), 6)


def map_row(row: dict[str, str]) -> dict[str, Any]:
    job_id = _text(row, "job_id") or _text(row, "title") or "unknown"
    risk = risk_score(row)
    relevance = relevance_score(row)
    profile = {
        "id": f"emscad:{job_id}",
        "age": 35,
        "anniversary": False,
        "channel": "direct",
        "colorway": "midnight-sapphire",
        "era_year": 1500,
        "entity_type": "job_profile",
        "title": _text(row, "title") or "Untitled job posting",
        "description": "\n\n".join(_text(row, field) for field in TEXT_FIELDS if _text(row, field)),
        "attributes": {
            "location": _text(row, "location"),
            "department": _text(row, "department"),
            "employment_type": _text(row, "employment_type"),
            "required_experience": _text(row, "required_experience"),
            "required_education": _text(row, "required_education"),
            "industry": _text(row, "industry"),
            "function": _text(row, "function"),
            "salary_range": _text(row, "salary_range"),
        },
        "signals": {
            "fraud_risk_score": risk,
            "telecommuting": _flag(row, "telecommuting"),
            "has_company_logo": _flag(row, "has_company_logo"),
            "has_questions": _flag(row, "has_questions"),
        },
        "evidence_quality_score": round(max(0.25, 1.0 - risk), 6),
        "source_relevance_score": relevance,
    }
    fraudulent = _flag(row, "fraudulent") == 1
    return {
        "profile": profile,
        "fraudulent": fraudulent,
        "risk_score": risk,
        "source_relevance_score": relevance,
        "source": "EMSCAD",
    }


def export(input_path: Path, output_path: Path, limit: int | None = None) -> dict[str, Any]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    fraudulent = 0
    with input_path.open("r", encoding="utf-8-sig", newline="") as source, output_path.open("w", encoding="utf-8", newline="\n") as target:
        for row in csv.DictReader(source):
            if limit is not None and count >= limit:
                break
            record = map_row(row)
            target.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
            count += 1
            fraudulent += int(record["fraudulent"])
    if count == 0:
        raise ValueError("input CSV produced no records")
    return {
        "records": count,
        "fraudulent": fraudulent,
        "legitimate": count - fraudulent,
        "fraudRate": fraudulent / count,
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert EMSCAD fake-job CSV rows into Valence fraud benchmark JSONL")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(export(args.input, args.output, args.limit), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
