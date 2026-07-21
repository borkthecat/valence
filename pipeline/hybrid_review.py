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


def _valid_label_studio_span(text: str, result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("value")
    if not isinstance(value, dict):
        raise ValueError("PII result is missing a value object")
    start, end, span_text = value.get("start"), value.get("end"), value.get("text")
    labels = value.get("labels")
    if not isinstance(start, int) or not isinstance(end, int) or not isinstance(span_text, str):
        raise ValueError("PII result is missing typed offsets or text")
    if not isinstance(labels, list) or len(labels) != 1 or labels[0] not in PII_LABELS:
        raise ValueError("PII result has an unsupported category")
    if not 0 <= start < end <= len(text) or text[start:end] != span_text:
        raise ValueError("PII result offsets do not exactly match task text")
    score = result.get("score", 0.0)
    if not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
        raise ValueError("PII result has an invalid score")
    return {
        "id": str(result.get("id") or hashlib.sha256(f"{start}:{end}:{labels[0]}".encode("utf-8")).hexdigest()),
        "from_name": "pii",
        "to_name": "text",
        "type": "labels",
        "value": {"start": start, "end": end, "text": span_text, "labels": labels},
        "score": float(score),
    }


def audit_pii_label_studio_tasks(tasks: list[dict[str, Any]]) -> dict[str, int]:
    if not tasks:
        raise ValueError("PII task export is empty")
    result_ids: set[str] = set()
    spans = 0
    for index, task in enumerate(tasks):
        if any(key in task for key in ("annotations", "truth", "entities", "gold")):
            raise ValueError(f"task {index} contains forbidden reviewer or gold fields")
        data = task.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("text"), str) or not data["text"]:
            raise ValueError(f"task {index} is missing display text")
        predictions = task.get("predictions")
        if not isinstance(predictions, list) or len(predictions) != 1 or not isinstance(predictions[0], dict):
            raise ValueError(f"task {index} must contain exactly one model prediction")
        results = predictions[0].get("result")
        if not isinstance(results, list):
            raise ValueError(f"task {index} prediction is missing results")
        for result in results:
            if not isinstance(result, dict):
                raise ValueError(f"task {index} contains an invalid result")
            valid = _valid_label_studio_span(data["text"], result)
            if valid["id"] in result_ids:
                raise ValueError(f"task {index} reuses a result ID")
            result_ids.add(valid["id"])
            spans += 1
    return {"tasks": len(tasks), "spans": spans, "unique_result_ids": len(result_ids)}


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
        explicit_id = source.get("id") or source.get("record_id")
        if not isinstance(explicit_id, str) or not explicit_id:
            raise ValueError(f"source record {index} requires a stable ID for prediction matching")
        record_id = explicit_id
        prediction = by_cache_id.get(record_id)
        if prediction is None:
            raise ValueError(f"source record {record_id} has no prediction with the same ID")
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


def build_pii_tasks_from_label_studio(
    source_tasks: list[dict[str, Any]],
    *,
    limit: int,
    calibration_count: int,
    minimum_score: float = 0.3,
) -> list[dict[str, Any]]:
    if not 0 <= minimum_score <= 1:
        raise ValueError("minimum_score must be between 0 and 1")
    audit_pii_label_studio_tasks(source_tasks)
    eligible: list[dict[str, Any]] = []
    for index, source_task in enumerate(source_tasks):
        data = source_task["data"]
        text = data["text"]
        explicit_source_id = data.get("source_id") or data.get("record_id")
        if not isinstance(explicit_source_id, str) or not explicit_source_id:
            raise ValueError(f"source task {index} requires a stable source ID")
        source_id = explicit_source_id
        results = source_task["predictions"][0]["result"]
        spans = [_valid_label_studio_span(text, result) for result in results if float(result.get("score", 0.0)) >= minimum_score]
        uncertain = any(0.3 <= float(span["score"]) <= 0.7 for span in spans)
        if not uncertain:
            continue
        record_id = f"{source_id}:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
        eligible.append({"record_id": record_id, "text": text, "spans": spans, "uncertain": True})
    if not eligible:
        raise ValueError("no uncertain PII tasks remain after score filtering")
    selected = _select_diverse_pii_rows(eligible, limit)
    calibration_ids = {row["record_id"] for row in _stable_order(selected, "record_id")[:calibration_count]}
    tasks = [
        {
            "data": {"record_id": row["record_id"], "text": row["text"], "ai_span_count": len(row["spans"])},
            "meta": {"review_kind": "pii", "review_stage": "calibration" if row["record_id"] in calibration_ids else "pilot", "priority": "uncertain", "model_assisted": True, "gold_labels_included": False},
            "predictions": [{"model_version": "valence-gliner-offset-validated", "result": row["spans"]}],
        }
        for row in selected
    ]
    audit_pii_label_studio_tasks(tasks)
    return tasks


def _ai_annotation_record_id(task: dict[str, Any], index: int) -> str:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"source task {index} is missing data")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError(f"source task {index} requires a stable record ID")
    return record_id


def build_pii_ai_annotation_packet(source_tasks: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Export clean text only so an independent AI cannot copy prior suggestions."""
    audit_pii_label_studio_tasks(source_tasks)
    packet: list[dict[str, str]] = []
    record_ids: set[str] = set()
    for index, task in enumerate(source_tasks):
        record_id = _ai_annotation_record_id(task, index)
        if record_id in record_ids:
            raise ValueError(f"source task {index} reuses record ID {record_id}")
        record_ids.add(record_id)
        packet.append({"record_id": record_id, "text": task["data"]["text"]})
    return _stable_order(packet, "record_id")


def _ai_span(text: str, record_id: str, entity: dict[str, Any]) -> dict[str, Any]:
    label, entity_text, occurrence = entity.get("label"), entity.get("text"), entity.get("occurrence", 1)
    if not isinstance(label, str) or label not in PII_LABELS:
        raise ValueError(f"AI annotation {record_id} has an unsupported label")
    if not isinstance(entity_text, str) or not entity_text:
        raise ValueError(f"AI annotation {record_id} is missing exact entity text")
    if not isinstance(occurrence, int) or occurrence < 1:
        raise ValueError(f"AI annotation {record_id} has an invalid occurrence")
    starts: list[int] = []
    start = text.find(entity_text)
    while start >= 0:
        starts.append(start)
        start = text.find(entity_text, start + len(entity_text))
    if len(starts) < occurrence:
        raise ValueError(f"AI annotation {record_id} text does not match occurrence {occurrence}")
    start = starts[occurrence - 1]
    end = start + len(entity_text)
    result_id = hashlib.sha256(f"{record_id}:{start}:{end}:{label}".encode("utf-8")).hexdigest()
    return {
        "id": result_id,
        "from_name": "pii",
        "to_name": "text",
        "type": "labels",
        "value": {"start": start, "end": end, "text": entity_text, "labels": [label]},
        "score": 1.0,
    }


def build_pii_tasks_from_ai_annotations(
    source_tasks: list[dict[str, Any]], ai_annotations: list[dict[str, Any]], *, model_version: str,
) -> list[dict[str, Any]]:
    """Convert text-only AI annotations into offset-validated silver Label Studio tasks."""
    if not model_version.strip():
        raise ValueError("model_version is required")
    packet = build_pii_ai_annotation_packet(source_tasks)
    source_by_id = {row["record_id"]: row for row in packet}
    annotations_by_id: dict[str, dict[str, Any]] = {}
    for index, annotation in enumerate(ai_annotations):
        if not isinstance(annotation, dict):
            raise ValueError(f"AI annotation {index} must be an object")
        record_id = annotation.get("record_id")
        entities = annotation.get("entities")
        if not isinstance(record_id, str) or record_id not in source_by_id:
            raise ValueError(f"AI annotation {index} has an unknown record ID")
        if not isinstance(entities, list):
            raise ValueError(f"AI annotation {record_id} is missing entities")
        if record_id in annotations_by_id:
            raise ValueError(f"AI annotation {record_id} appears more than once")
        annotations_by_id[record_id] = annotation
    if set(annotations_by_id) != set(source_by_id):
        raise ValueError("AI annotations must cover every source record exactly once")
    tasks: list[dict[str, Any]] = []
    for row in packet:
        annotation = annotations_by_id[row["record_id"]]
        results = [_ai_span(row["text"], row["record_id"], entity) for entity in annotation["entities"]]
        ordered = sorted(results, key=lambda result: (result["value"]["start"], result["value"]["end"], result["value"]["labels"][0]))
        for previous, current in zip(ordered, ordered[1:]):
            if current["value"]["start"] < previous["value"]["end"]:
                raise ValueError(f"AI annotation {row['record_id']} contains overlapping entities")
        tasks.append({
            "data": {"record_id": row["record_id"], "text": row["text"], "ai_span_count": len(ordered)},
            "meta": {"review_kind": "pii", "review_stage": "ai_silver", "model_assisted": True, "human_review_required": True, "gold_labels_included": False},
            "predictions": [{"model_version": model_version, "result": ordered}],
        })
    audit_pii_label_studio_tasks(tasks)
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
