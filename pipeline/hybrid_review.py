"""Build and reconcile human-in-the-loop review artifacts without label leakage."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


PII_LABELS = {
    "PERSON_NAME",
    "EMAIL",
    "PHONE",
    "ADDRESS",
    "API_KEY",
    "PASSWORD",
    "SSN",
    "CREDIT_CARD",
    "GENERIC_SECRET",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain an object")
            rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stable_order(rows: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: hashlib.sha256(str(row[key]).encode("utf-8")).hexdigest())


def _text(row: dict[str, Any], name: str) -> str:
    value = row.get(name) or row.get("text") or row.get("source_text")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"record {row.get('id', '<unknown>')} is missing non-empty {name}")
    return value


def _prediction_result(text: str, prediction: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for span in prediction.get("predictions", []):
        category = str(span.get("category") or span.get("label") or "")
        start, end = span.get("start"), span.get("end")
        if category not in PII_LABELS or not isinstance(start, int) or not isinstance(end, int):
            continue
        if not 0 <= start < end <= len(text):
            continue
        result.append({
            "from_name": "pii",
            "to_name": "text",
            "type": "labels",
            "value": {"start": start, "end": end, "text": text[start:end], "labels": [category]},
            "score": float(span.get("score", 0.0)),
        })
    return result


def _pii_sampling_key(row: dict[str, Any]) -> tuple[float, str]:
    uncertainty = min(
        abs(float(span["score"]) - 0.5)
        for span in row["spans"]
        if 0.3 <= float(span["score"]) <= 0.7
    )
    return uncertainty, hashlib.sha256(str(row["record_id"]).encode("utf-8")).hexdigest()


def _pii_span_category(span: dict[str, Any]) -> str:
    value = span.get("value")
    if isinstance(value, dict):
        labels = value.get("labels")
        if isinstance(labels, list) and labels and isinstance(labels[0], str):
            return labels[0]
    raise ValueError("PII prediction is missing a Label Studio category")


def _select_diverse_pii_rows(eligible: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or limit >= len(eligible):
        return _stable_order(eligible, "record_id")
    candidates: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        for category in {_pii_span_category(span) for span in row["spans"] if 0.3 <= float(span["score"]) <= 0.7}:
            candidates.setdefault(category, []).append(row)
    for category in candidates:
        candidates[category].sort(key=_pii_sampling_key)
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    positions = {category: 0 for category in candidates}
    while len(selected) < limit:
        added = False
        for category in sorted(candidates):
            rows = candidates[category]
            position = positions[category]
            while position < len(rows) and str(rows[position]["record_id"]) in selected_ids:
                position += 1
            positions[category] = position
            if position >= len(rows):
                continue
            row = rows[position]
            positions[category] += 1
            selected.append(row)
            selected_ids.add(str(row["record_id"]))
            added = True
            if len(selected) == limit:
                break
        if not added:
            break
    if len(selected) < limit:
        for row in sorted(eligible, key=_pii_sampling_key):
            if str(row["record_id"]) not in selected_ids:
                selected.append(row)
                selected_ids.add(str(row["record_id"]))
                if len(selected) == limit:
                    break
    return _stable_order(selected, "record_id")


def build_pii_tasks(
    source_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    *,
    limit: int,
    calibration_count: int,
    uncertain_only: bool,
) -> list[dict[str, Any]]:
    """Create Label Studio tasks while intentionally excluding every gold-label field."""
    by_cache_id = {str(row.get("record_id")): row for row in prediction_rows}
    eligible: list[dict[str, Any]] = []
    for index, source in enumerate(source_rows):
        record_id = str(source.get("id") or source.get("record_id") or f"record-{index}")
        prediction = by_cache_id.get(record_id) or by_cache_id.get(f"record-{index}")
        if prediction is None:
            continue
        text = _text(source, "text")
        spans = _prediction_result(text, prediction)
        uncertain = any(0.3 <= float(span["score"]) <= 0.7 for span in spans)
        if uncertain_only and not uncertain:
            continue
        eligible.append({"record_id": record_id, "text": text, "spans": spans, "uncertain": uncertain})
    if not eligible:
        raise ValueError("no PII review tasks matched the input and prediction cache")
    eligible = _select_diverse_pii_rows(eligible, limit)
    calibration_ids = {row["record_id"] for row in _stable_order(eligible, "record_id")[:calibration_count]}
    tasks: list[dict[str, Any]] = []
    for row in eligible:
        task = {
            "data": {"record_id": row["record_id"], "text": row["text"], "ai_span_count": len(row["spans"])},
            "meta": {
                "review_kind": "pii",
                "review_stage": "calibration" if row["record_id"] in calibration_ids else "pilot",
                "priority": "uncertain" if row["uncertain"] else "standard",
                "model_assisted": True,
                "gold_labels_included": False,
            },
            "predictions": [{"model_version": "valence-pii-ensemble", "result": row["spans"]}],
        }
        tasks.append(task)
    return tasks


def _nested_text(row: dict[str, Any], parent: str, keys: tuple[str, ...]) -> str | None:
    nested = row.get(parent)
    if not isinstance(nested, dict):
        return None
    for key in keys:
        value = nested.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def normalize_ranking_pair(row: dict[str, Any], index: int) -> dict[str, Any]:
    job_id = row.get("job_id") or (row.get("job") or {}).get("job_id")
    candidate_id = row.get("candidate_id") or (row.get("candidate") or {}).get("candidate_id")
    job_text = row.get("job_text") or _nested_text(row, "job", ("text", "description", "requirements"))
    candidate_text = row.get("candidate_text") or _nested_text(row, "candidate", ("text", "profile", "evidence"))
    if not all(isinstance(value, str) and value.strip() for value in (job_id, candidate_id, job_text, candidate_text)):
        raise ValueError(f"ranking pair {index} requires job_id, candidate_id, job_text, and candidate_text")
    score = row.get("ai_score", row.get("score", ""))
    if score != "" and (not isinstance(score, int) or not 0 <= score <= 3):
        raise ValueError(f"ranking pair {index} ai_score must be an integer in 0..3 when supplied")
    return {
        "job_id": str(job_id),
        "candidate_id": str(candidate_id),
        "job_text": str(job_text),
        "candidate_text": str(candidate_text),
        "ai_score": score if isinstance(score, int) else None,
        "ai_rationale": str(row.get("ai_rationale") or row.get("rationale") or ""),
    }


def build_ranking_tasks(pairs: list[dict[str, Any]], *, calibration_jobs: int, strict_pilot: bool) -> list[dict[str, Any]]:
    normalized = [normalize_ranking_pair(row, index) for index, row in enumerate(pairs)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        grouped.setdefault(row["job_id"], []).append(row)
    if strict_pilot and len(grouped) != 210:
        raise ValueError(f"human ranking pilot requires exactly 210 jobs, received {len(grouped)}")
    for job_id, group in grouped.items():
        candidate_ids = [row["candidate_id"] for row in group]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError(f"job {job_id} has duplicate candidate IDs")
        if strict_pilot and not 10 <= len(group) <= 20:
            raise ValueError(f"job {job_id} requires 10 to 20 candidates, received {len(group)}")
    calibration_set = {row["job_id"] for row in _stable_order([{"job_id": key} for key in grouped], "job_id")[:calibration_jobs]}
    tasks: list[dict[str, Any]] = []
    for job_id in sorted(grouped):
        for rank, row in enumerate(sorted(grouped[job_id], key=lambda item: (-(item["ai_score"] if item["ai_score"] is not None else -1), item["candidate_id"])), start=1):
            tasks.append({
                "data": {**row, "ai_rank": rank},
                "meta": {
                    "review_kind": "ranking",
                    "review_stage": "calibration" if job_id in calibration_set else "pilot",
                    "model_assisted": True,
                    "gold_labels_included": False,
                },
            })
    return tasks


def latest_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    annotations = [item for item in task.get("annotations", []) if not item.get("was_cancelled")]
    if not annotations:
        return None
    return max(annotations, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))


def choice(annotation: dict[str, Any], name: str) -> str | None:
    for result in annotation.get("result", []):
        if result.get("from_name") == name:
            values = result.get("value", {}).get("choices", [])
            if values:
                return str(values[0])
    return None


def pii_spans(annotation: dict[str, Any]) -> set[tuple[int, int, str]]:
    spans: set[tuple[int, int, str]] = set()
    for result in annotation.get("result", []):
        if result.get("from_name") != "pii":
            continue
        value = result.get("value", {})
        labels = value.get("labels", [])
        if labels and isinstance(value.get("start"), int) and isinstance(value.get("end"), int):
            spans.add((value["start"], value["end"], str(labels[0])))
    return spans


def cohen_kappa(left: list[str], right: list[str]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("kappa requires equal, non-empty label lists")
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum((left_counts[key] / len(left)) * (right_counts[key] / len(right)) for key in set(left_counts) | set(right_counts))
    return 1.0 if expected == 1.0 and observed == 1.0 else (observed - expected) / (1.0 - expected)
