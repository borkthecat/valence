"""Deterministic, deidentified ATS export adapters for pre-label intake."""
from __future__ import annotations

import csv
import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

FORMAT_VERSION = "1"
REQUIRED = ("case_id", "job_id", "candidate_id")


@dataclass(frozen=True, slots=True)
class CanonicalTalentRow:
    case_id: str
    job_id: str
    candidate_id: str
    source_system: str
    job_title: str = ""
    claimed_skills: tuple[str, ...] = ()
    experience_years: float | None = None
    region: str = ""


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    format_version: str
    source_system: str
    records: int
    source_digest: str
    canonical_digest: str


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _skills(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return tuple(sorted({_text(item).casefold() for item in values if _text(item)}))


def normalize_row(row: dict[str, Any], source_system: str) -> CanonicalTalentRow:
    missing = [key for key in REQUIRED if not _text(row.get(key))]
    if missing:
        raise ValueError(f"missing required adapter fields: {missing}")
    experience = row.get("experience_years")
    parsed = None if experience in (None, "") else float(experience)
    if parsed is not None and not 0 <= parsed <= 80:
        raise ValueError("experience_years must be between 0 and 80")
    return CanonicalTalentRow(
        case_id=_text(row["case_id"]), job_id=_text(row["job_id"]),
        candidate_id=_text(row["candidate_id"]), source_system=_text(source_system),
        job_title=_text(row.get("job_title")), claimed_skills=_skills(row.get("claimed_skills")),
        experience_years=parsed, region=_text(row.get("region")).casefold(),
    )


def _canonical_bytes(rows: Iterable[CanonicalTalentRow]) -> bytes:
    payload = [asdict(row) for row in sorted(rows, key=lambda item: (item.case_id, item.candidate_id))]
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()


def adapt(path: Path, *, source_system: str) -> tuple[tuple[CanonicalTalentRow, ...], AdapterManifest]:
    raw = path.read_bytes()
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
    elif suffix == ".jsonl":
        source_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif suffix == ".json":
        parsed = json.loads(path.read_text(encoding="utf-8"))
        source_rows = parsed["records"] if isinstance(parsed, dict) else parsed
    else:
        raise ValueError("adapter input must be CSV, JSON, or JSONL")
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("adapter input must contain records")
    rows = tuple(normalize_row(row, source_system) for row in source_rows)
    keys = [(row.case_id, row.candidate_id) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate case/candidate adapter key")
    canonical = _canonical_bytes(rows)
    return rows, AdapterManifest(FORMAT_VERSION, source_system, len(rows), _digest(raw), _digest(canonical))


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a deidentified ATS export")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-system", required=True)
    args = parser.parse_args()
    rows, manifest = adapt(args.input, source_system=args.source_system)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(asdict(row), sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")
    args.manifest.write_text(json.dumps(asdict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
