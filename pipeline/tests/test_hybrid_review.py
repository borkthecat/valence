from __future__ import annotations

from hybrid_review import build_pii_tasks, build_ranking_tasks, cohen_kappa


def test_pii_review_tasks_never_export_gold_entities() -> None:
    tasks = build_pii_tasks(
        [{"id": "source-1", "text": "Contact Ada at ada@example.test", "entities": [{"start": 8, "end": 11, "label": "PERSON_NAME"}]}],
        [{"record_id": "record-0", "truth": [{"start": 8, "end": 11, "category": "PERSON_NAME"}], "predictions": [{"start": 8, "end": 11, "category": "PERSON_NAME", "score": 0.5}]}],
        limit=1, calibration_count=1, uncertain_only=True,
    )
    assert tasks[0]["data"]["record_id"] == "source-1"
    assert tasks[0]["meta"]["gold_labels_included"] is False
    assert "entities" not in tasks[0]["data"]
    assert "truth" not in str(tasks[0])
    assert tasks[0]["predictions"][0]["result"][0]["value"]["labels"] == ["PERSON_NAME"]


def test_pii_review_tasks_balance_uncertain_categories() -> None:
    source = [{"id": f"source-{index}", "text": f"record {index}"} for index in range(6)]
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
