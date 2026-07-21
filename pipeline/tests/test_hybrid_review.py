from __future__ import annotations

from hybrid_review import (
    audit_pii_label_studio_tasks,
    build_pii_ai_annotation_packet,
    build_pii_tasks,
    build_pii_tasks_from_ai_annotations,
    build_pii_tasks_from_label_studio,
    build_ranking_tasks,
    cohen_kappa,
)


def test_pii_review_tasks_never_export_gold_entities() -> None:
    tasks = build_pii_tasks(
        [{"id": "record-0", "text": "Contact Ada at ada@example.test", "entities": [{"start": 8, "end": 11, "label": "PERSON_NAME"}]}],
        [{"record_id": "record-0", "truth": [{"start": 8, "end": 11, "category": "PERSON_NAME"}], "predictions": [{"start": 8, "end": 11, "category": "PERSON_NAME", "score": 0.5}]}],
        limit=1, calibration_count=1, uncertain_only=True,
    )
    assert tasks[0]["data"]["record_id"] == "record-0"
    assert tasks[0]["meta"]["gold_labels_included"] is False
    assert "entities" not in tasks[0]["data"]
    assert "truth" not in str(tasks[0])
    assert tasks[0]["predictions"][0]["result"][0]["value"]["labels"] == ["PERSON_NAME"]


def test_pii_review_tasks_reject_mismatched_source_and_prediction_ids() -> None:
    try:
        build_pii_tasks(
            [{"id": "nemotron:source-1", "text": "Contact Ada"}],
            [{"record_id": "record-0", "predictions": []}],
            limit=1, calibration_count=1, uncertain_only=True,
        )
    except ValueError as error:
        assert "same ID" in str(error)
    else:
        raise AssertionError("mismatched source and prediction IDs must fail")


def test_pii_review_tasks_reject_source_without_stable_id() -> None:
    try:
        build_pii_tasks(
            [{"text": "Contact Ada"}],
            [{"record_id": "record-0", "predictions": []}],
            limit=1, calibration_count=1, uncertain_only=True,
        )
    except ValueError as error:
        assert "stable ID" in str(error)
    else:
        raise AssertionError("source without stable ID must fail")


def test_offset_validated_label_studio_tasks_are_safe_for_review() -> None:
    source = [{
        "data": {"source_id": "source-1", "text": "Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "entity-1", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Ada", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    tasks = build_pii_tasks_from_label_studio(source, limit=1, calibration_count=1)
    assert tasks[0]["data"]["text"] == "Ada at ada@example.test"
    assert audit_pii_label_studio_tasks(tasks) == {"tasks": 1, "spans": 1, "unique_result_ids": 1}


def test_offset_validated_label_studio_tasks_reject_mismatched_span() -> None:
    source = [{
        "data": {"source_id": "source-1", "text": "Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "entity-1", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Wrong", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    try:
        build_pii_tasks_from_label_studio(source, limit=1, calibration_count=1)
    except ValueError as error:
        assert "offsets" in str(error)
    else:
        raise AssertionError("mismatched span must fail")


def test_offset_validated_label_studio_tasks_require_stable_source_id() -> None:
    source = [{
        "data": {"text": "Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "entity-1", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Ada", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    try:
        build_pii_tasks_from_label_studio(source, limit=1, calibration_count=1)
    except ValueError as error:
        assert "stable source ID" in str(error)
    else:
        raise AssertionError("source task without stable ID must fail")


def test_ai_annotation_import_computes_offsets_from_exact_text() -> None:
    source = [{
        "data": {"record_id": "record-1", "text": "Ada emailed Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "source-entity", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Ada", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    assert build_pii_ai_annotation_packet(source) == [{"record_id": "record-1", "text": "Ada emailed Ada at ada@example.test"}]
    tasks = build_pii_tasks_from_ai_annotations(source, [{
        "record_id": "record-1",
        "entities": [
            {"label": "PERSON_NAME", "text": "Ada", "occurrence": 2},
            {"label": "EMAIL", "text": "ada@example.test"},
        ],
    }], model_version="external-ai-silver")
    results = tasks[0]["predictions"][0]["result"]
    assert [(result["value"]["start"], result["value"]["text"]) for result in results] == [(12, "Ada"), (19, "ada@example.test")]
    assert tasks[0]["meta"]["human_review_required"] is True


def test_ai_annotation_import_rejects_nonexistent_text() -> None:
    source = [{
        "data": {"record_id": "record-1", "text": "Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "source-entity", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Ada", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    try:
        build_pii_tasks_from_ai_annotations(source, [{
            "record_id": "record-1", "entities": [{"label": "PERSON_NAME", "text": "Wrong"}],
        }], model_version="external-ai-silver")
    except ValueError as error:
        assert "does not match" in str(error)
    else:
        raise AssertionError("AI text not present in the source must fail")


def test_ai_annotation_packet_uses_deterministic_source_id_when_record_id_is_absent() -> None:
    source = [{
        "data": {"source_id": "nemotron:source-1", "text": "Ada at ada@example.test"},
        "predictions": [{"model_version": "gliner", "result": [{
            "id": "source-entity", "from_name": "pii", "to_name": "text", "type": "labels", "score": 0.5,
            "value": {"start": 0, "end": 3, "text": "Ada", "labels": ["PERSON_NAME"]},
        }]}],
    }]
    packet = build_pii_ai_annotation_packet(source)
    assert packet[0]["record_id"].startswith("nemotron:source-1:")
    tasks = build_pii_tasks_from_ai_annotations(source, [{
        "record_id": packet[0]["record_id"], "entities": [],
    }], model_version="external-ai-silver")
    assert tasks[0]["data"]["record_id"] == packet[0]["record_id"]


def test_pii_review_tasks_balance_uncertain_categories() -> None:
    source = [{"id": f"record-{index}", "text": f"record {index}"} for index in range(6)]
    predictions = [
        {"record_id": "record-0", "predictions": [{"start": 0, "end": 1, "category": "PERSON_NAME", "score": 0.5}]},
        {"record_id": "record-1", "predictions": [{"start": 0, "end": 1, "category": "PERSON_NAME", "score": 0.49}]},
        {"record_id": "record-2", "predictions": [{"start": 0, "end": 1, "category": "EMAIL", "score": 0.5}]},
        {"record_id": "record-3", "predictions": [{"start": 0, "end": 1, "category": "EMAIL", "score": 0.49}]},
        {"record_id": "record-4", "predictions": [{"start": 0, "end": 1, "category": "SSN", "score": 0.5}]},
        {"record_id": "record-5", "predictions": [{"start": 0, "end": 1, "category": "SSN", "score": 0.49}]},
    ]
    tasks = build_pii_tasks(source, predictions, limit=3, calibration_count=3, uncertain_only=True)
    categories = {task["predictions"][0]["result"][0]["value"]["labels"][0] for task in tasks}
    assert categories == {"PERSON_NAME", "EMAIL", "SSN"}


def test_ranking_pilot_rejects_wrong_job_count() -> None:
    pair = {"job_id": "job-1", "candidate_id": "candidate-1", "job_text": "Need Python", "candidate_text": "Python engineer"}
    try:
        build_ranking_tasks([pair], calibration_jobs=1, strict_pilot=True)
    except ValueError as error:
        assert "exactly 210 jobs" in str(error)
    else:
        raise AssertionError("strict pilot must reject incomplete input")


def test_ranking_smoke_tasks_mark_calibration_and_preserve_ai_score() -> None:
    tasks = build_ranking_tasks([
        {"job_id": "job-1", "candidate_id": "candidate-2", "job_text": "Need Python", "candidate_text": "Python", "ai_score": 2},
        {"job_id": "job-1", "candidate_id": "candidate-1", "job_text": "Need Python", "candidate_text": "Python and SQL", "ai_score": 3},
    ], calibration_jobs=1, strict_pilot=False)
    assert len(tasks) == 2
    assert all(task["meta"]["review_stage"] == "calibration" for task in tasks)
    assert tasks[0]["data"]["ai_rank"] == 1


def test_cohen_kappa_reports_perfect_agreement() -> None:
    assert cohen_kappa(["0", "1", "2", "3"], ["0", "1", "2", "3"]) == 1.0
