"""Export the held-out NVIDIA Nemotron-PII split to the gateway JSONL contract."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

DATASET = "nvidia/Nemotron-PII"

# The gateway evaluates its current compact taxonomy.  Related PII concepts are
# intentionally collapsed only where the detector has a matching enforcement class.
LABEL_MAP = {
    "account_number": "GENERIC_SECRET",
    "age": "GENERIC_SECRET",
    "api_key": "API_KEY",
    "bank_routing_number": "GENERIC_SECRET",
    "biometric_identifier": "GENERIC_SECRET",
    "blood_type": "GENERIC_SECRET",
    "certificate_license_number": "GENERIC_SECRET",
    "city": "GENERIC_SECRET",
    "company_name": "GENERIC_SECRET",
    "coordinate": "GENERIC_SECRET",
    "country": "GENERIC_SECRET",
    "county": "GENERIC_SECRET",
    "credit_debit_card": "CREDIT_CARD",
    "customer_id": "GENERIC_SECRET",
    "cvv": "GENERIC_SECRET",
    "date": "GENERIC_SECRET",
    "date_of_birth": "GENERIC_SECRET",
    "date_time": "GENERIC_SECRET",
    "device_identifier": "GENERIC_SECRET",
    "education_level": "GENERIC_SECRET",
    "email": "EMAIL",
    "employee_id": "GENERIC_SECRET",
    "employment_status": "GENERIC_SECRET",
    "fax_number": "PHONE",
    "first_name": "PERSON_NAME",
    "gender": "GENERIC_SECRET",
    "health_plan_beneficiary_number": "GENERIC_SECRET",
    "http_cookie": "ACCESS_TOKEN",
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    "language": "GENERIC_SECRET",
    "last_name": "PERSON_NAME",
    "license_plate": "GENERIC_SECRET",
    "mac_address": "GENERIC_SECRET",
    "medical_record_number": "GENERIC_SECRET",
    "national_id": "GENERIC_SECRET",
    "occupation": "GENERIC_SECRET",
    "password": "PASSWORD",
    "phone_number": "PHONE",
    "pin": "PASSWORD",
    "political_view": "GENERIC_SECRET",
    "postcode": "GENERIC_SECRET",
    "race_ethnicity": "GENERIC_SECRET",
    "religious_belief": "GENERIC_SECRET",
    "sexuality": "GENERIC_SECRET",
    "ssn": "SSN",
    "state": "GENERIC_SECRET",
    "street_address": "GENERIC_SECRET",
    "swift_bic": "GENERIC_SECRET",
    "tax_id": "GENERIC_SECRET",
    "time": "GENERIC_SECRET",
    "unique_id": "GENERIC_SECRET",
    "url": "GENERIC_SECRET",
    "user_name": "GENERIC_SECRET",
    "vehicle_identifier": "GENERIC_SECRET",
}


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    text = row.get("text")
    uid = row.get("uid")
    if not isinstance(text, str) or not isinstance(uid, str):
        raise ValueError("Nemotron row needs string text and uid")
    raw_spans = row.get("spans")
    if not isinstance(raw_spans, str):
        raise ValueError(f"Nemotron row {uid} has non-string spans")
    parsed = ast.literal_eval(raw_spans)
    if not isinstance(parsed, list):
        raise ValueError(f"Nemotron row {uid} spans must be a list")
    entities: list[dict[str, int | str]] = []
    for span in parsed:
        if not isinstance(span, dict):
            raise ValueError(f"Nemotron row {uid} contains a non-object span")
        start, end, label = span.get("start"), span.get("end"), span.get("label")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(label, str):
            raise ValueError(f"Nemotron row {uid} span is missing start/end/label")
        if start < 0 or end <= start or end > len(text):
            raise ValueError(f"Nemotron row {uid} has an out-of-range span")
        mapped = LABEL_MAP.get(label)
        if mapped is None:
            raise ValueError(f"Nemotron row {uid} uses unmapped label {label!r}")
        entities.append({"start": start, "end": end, "label": mapped})
    return {
        "id": f"nemotron:{uid}",
        "text": text,
        "entities": entities,
        "provenance": {
            "dataset": DATASET,
            "split": "test",
            "uid": uid,
            "locale": row.get("locale"),
            "domain": row.get("domain"),
            "synthetic": True,
            "releaseEvidence": False,
        },
    }


def select(rows: Iterable[dict[str, Any]], rows_limit: int) -> list[dict[str, Any]]:
    selected = [normalize_record(row) for row in rows]
    selected.sort(key=lambda row: hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest())
    return selected[:rows_limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export NVIDIA Nemotron-PII held-out records")
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 50_000:
        raise ValueError("--rows must be between 1 and 50000")
    try:
        from datasets import load_dataset
    except ImportError as error:
        raise RuntimeError("datasets is required; install pipeline/requirements.txt") from error
    dataset = load_dataset(DATASET, split="test")
    records = select(dataset, args.rows)
    if len(records) != args.rows:
        raise RuntimeError(f"requested {args.rows} records, found {len(records)}")
    labels = Counter(entity["label"] for record in records for entity in record["entities"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    print(json.dumps({
        "dataset": DATASET,
        "split": "test",
        "records": len(records),
        "mappedEntities": sum(labels.values()),
        "mappedLabels": dict(sorted(labels.items())),
        "selection": "sha256(uid)-ordered-prefix",
        "releaseEvidence": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
