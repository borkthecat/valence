"""Synthetic fixtures exercise contracts only; they are not pilot data."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from talent_evaluator import evaluate, evaluate_by_slice
from talent_schema import TalentEvaluationRecord, TalentEvaluationSubmission


def _record() -> TalentEvaluationRecord:
    return TalentEvaluationRecord.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "case-001",
            "dataset_version": "pilot-contract-fixture",
            "split": "pilot",
            "job": {
                "job_id": "job-001",
                "title": "Backend engineer",
                "job_family": "engineering",
                "seniority": "senior",
                "region": "apac",
                "language": "en",
                "policy_version": "policy-1",
                "jurisdiction": "SG",
            },
            "candidates": [
                {
                    "candidate_id": "candidate-a",
                    "profile_completeness": 0.9,
                    "source_system": "fixture",
                    "evidence": [{"evidence_id": "a", "source_type": "resume", "trust_level": "unverified", "content_hash": "sha256:" + "a" * 64, "observed_at": "2026-01-01", "verification_status": "unverified"}],
                },
                {"candidate_id": "candidate-b", "profile_completeness": 0.7, "source_system": "fixture", "evidence": []},
                {"candidate_id": "candidate-c", "profile_completeness": 0.3, "source_system": "fixture", "evidence": []},
            ],
            "annotations": {
                "reviewer_ids": ["reviewer-1", "reviewer-2"],
                "adjudication_status": "agreed",
                "annotation_version": "pilot-rubric-1",
                "candidate_annotations": {
                    "candidate-a": {"hard_eligibility": "pass", "graded_relevance": 3, "evidence_sufficiency": "sufficient", "fraud_or_inconsistency_risk": "none", "human_review_required": False, "reviewer_explanation": "Required skill evidenced.", "confidence": 0.9},
                    "candidate-b": {"hard_eligibility": "pass", "graded_relevance": 2, "evidence_sufficiency": "partial", "fraud_or_inconsistency_risk": "low", "human_review_required": True, "reviewer_explanation": "Some evidence needs review.", "confidence": 0.7},
                    "candidate-c": {"hard_eligibility": "fail", "graded_relevance": 0, "evidence_sufficiency": "insufficient", "fraud_or_inconsistency_risk": "medium", "human_review_required": True, "reviewer_explanation": "Required evidence absent.", "confidence": 0.8},
                },
            },
        }
    )


def _submission() -> TalentEvaluationSubmission:
    return TalentEvaluationSubmission.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "case-001",
            "policy_version": "policy-1",
            "model_version": "candidate-model-0",
            "ranked_candidate_ids": ["candidate-a", "candidate-b", "candidate-c"],
            "assessments": [
                {"candidate_id": "candidate-a", "eligibility": "pass", "evidence_sufficiency": "sufficient", "risk": "none", "uncertainty": 0.1, "human_review_required": False, "shortlist_eligible": True},
                {"candidate_id": "candidate-b", "eligibility": "pass", "evidence_sufficiency": "partial", "risk": "low", "uncertainty": 0.4, "human_review_required": True, "shortlist_eligible": True},
                {"candidate_id": "candidate-c", "eligibility": "fail", "evidence_sufficiency": "insufficient", "risk": "medium", "uncertainty": 0.8, "human_review_required": True, "shortlist_eligible": False},
            ],
        }
    )


def test_record_requires_annotations_for_every_candidate() -> None:
    payload = _record().model_dump(mode="json")
    del payload["annotations"]["candidate_annotations"]["candidate-c"]
    with pytest.raises(ValidationError, match="cover every candidate"):
        TalentEvaluationRecord.model_validate(payload)


def test_submission_rejects_duplicate_assessments() -> None:
    payload = _submission().model_dump(mode="json")
    payload["assessments"][2]["candidate_id"] = "candidate-b"
    with pytest.raises(ValidationError, match="assessment candidate ids must be unique"):
        TalentEvaluationSubmission.model_validate(payload)


def test_evaluator_reports_perfect_contract_fixture() -> None:
    report = evaluate([_record()], [_submission()])
    assert report.ndcg_at_5 == 1.0
    assert report.qualified_recall_at_5 == 1.0
    assert report.pairwise_preference_accuracy == 1.0
    assert report.top1_agreement == 1.0
    assert report.hard_eligibility_violation_rate == 0.0
    assert report.unsupported_evidence_promotion_rate == 0.0
    assert report.incorrect_automatic_exclusion_rate == 0.0


def test_evaluator_rejects_pending_annotation() -> None:
    record = _record()
    pending = record.model_copy(update={"annotations": record.annotations.model_copy(update={"adjudication_status": "pending"})})
    with pytest.raises(ValueError, match="agreed or adjudicated"):
        evaluate([pending], [_submission()])


def test_evaluator_supports_predeclared_dataset_slices() -> None:
    reports = evaluate_by_slice([_record()], [_submission()], "job_family")
    assert reports["engineering"].cases == 1
    with pytest.raises(ValueError, match="unsupported slice"):
        evaluate_by_slice([_record()], [_submission()], "protected_attribute")
