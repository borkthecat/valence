"""Synthetic fixtures exercise contracts only; they are not pilot data."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from talent_dataset_audit import audit_records
from talent_evaluator import bootstrap_confidence_intervals, evaluate, evaluate_by_slice
from talent_benchmark_manifest import BenchmarkManifest, canonical_digest, canonical_record_digest
from talent_review_adapter import review_to_evaluation_submission
from talent_schema import TalentEvaluationRecord, TalentEvaluationSubmission
from stage5_cognitive_verifier import CandidateJudgment, apply_review_policy

NOW = "2026-07-01T12:00:00+00:00"
DIGEST = "sha256:" + "a" * 64


def _label(eligibility: str, relevance: int, evidence: str, risk: str, review: bool, confidence: float = 0.8) -> dict[str, object]:
    return {"hard_eligibility": eligibility, "graded_relevance": relevance, "evidence_sufficiency": evidence, "fraud_or_inconsistency_risk": risk, "human_review_required": review, "explanation": "Fixture evidence rationale.", "confidence": confidence}


def _review(reviewer: str, adjustment: int = 0) -> dict[str, object]:
    labels = {
        "candidate-a": _label("pass", 3, "sufficient", "none", False, .9),
        "candidate-b": _label("pass", 2 + adjustment, "partial", "low", True, .7),
        "candidate-c": _label("fail", 0, "insufficient", "medium", True, .8),
    }
    return {"reviewer_id": reviewer, "candidate_annotations": [{**label, "reviewer_id": reviewer, "candidate_id": candidate_id, "completed_at": NOW, "rubric_version": "pilot-rubric-1"} for candidate_id, label in labels.items()]}


def _record() -> TalentEvaluationRecord:
    labels = {"candidate-a": _label("pass", 3, "sufficient", "none", False, .9), "candidate-b": _label("pass", 2, "partial", "low", True, .7), "candidate-c": _label("fail", 0, "insufficient", "medium", True, .8)}
    return TalentEvaluationRecord.model_validate({
        "schema_version": "1.1", "case_id": "case-001", "dataset_version": "pilot-contract-fixture", "split": "pilot",
        "job": {"job_id": "job-001", "title": "Backend engineer", "job_family": "engineering", "required_skills": ["python"], "seniority": "senior", "region": "apac", "language": "en", "policy_version": "policy-1", "jurisdiction": "SG"},
        "candidates": [
            {"candidate_id": "candidate-a", "claimed_skills": ["python"], "profile_completeness": .9, "source_system": "fixture", "evidence": [{"evidence_id": "evidence-a", "source_type": "resume", "trust_level": "unverified", "content_hash": DIGEST, "observed_at": NOW, "verification_status": "unverified", "claim_ids": ["claim-a"]}], "claims": [{"claim_id": "claim-a", "claim_type": "skill", "normalized_value": "python", "evidence_ids": ["evidence-a"], "verification_status": "unverified"}]},
            {"candidate_id": "candidate-b", "profile_completeness": .7, "source_system": "fixture"},
            {"candidate_id": "candidate-c", "profile_completeness": .3, "source_system": "fixture"},
        ],
        "annotations": {"independent_reviews": [_review("reviewer-1"), _review("reviewer-2")], "adjudicated_labels": labels, "adjudication_status": "agreed"},
        "provenance": {"source_system": "fixture", "export_id": "export-1", "export_timestamp": NOW, "collector_version": "collector-1", "transformation_version": "transform-1", "source_policy_version": "policy-1", "deidentification_version": "deid-1", "record_digest": DIGEST},
    })


def _submission() -> TalentEvaluationSubmission:
    return TalentEvaluationSubmission.model_validate({
        "schema_version": "1.1", "case_id": "case-001", "policy_version": "policy-1", "model_version": "candidate-model-0", "ranked_candidate_ids": ["candidate-a", "candidate-b", "candidate-c"],
        "assessments": [
            {"candidate_id": "candidate-a", "eligibility": "pass", "evidence_sufficiency": "sufficient", "risk": "none", "uncertainty": .1, "human_review_required": False, "shortlist_eligible": True},
            {"candidate_id": "candidate-b", "eligibility": "pass", "evidence_sufficiency": "partial", "risk": "low", "uncertainty": .4, "human_review_required": True, "shortlist_eligible": True},
            {"candidate_id": "candidate-c", "eligibility": "fail", "evidence_sufficiency": "insufficient", "risk": "medium", "uncertainty": .8, "human_review_required": True, "shortlist_eligible": False},
        ],
        "reproducibility": {"run_id": "run-1", "submitted_at": NOW, "evaluator_version": "eval-1", "model_artifact_digest": DIGEST, "policy_artifact_digest": DIGEST, "configuration_digest": DIGEST, "inference_provider": "fixture", "execution_environment": "test"},
    })


def test_record_requires_independent_coverage_for_every_candidate() -> None:
    payload = _record().model_dump(mode="json")
    payload["annotations"]["independent_reviews"][0]["candidate_annotations"].pop()
    with pytest.raises(ValidationError, match="cover every candidate"):
        TalentEvaluationRecord.model_validate(payload)


def test_submission_reconciles_ranking_and_assessments() -> None:
    payload = _submission().model_dump(mode="json")
    payload["assessments"][2]["candidate_id"] = "candidate-b"
    with pytest.raises(ValidationError, match="assessment candidate ids must be unique"):
        TalentEvaluationSubmission.model_validate(payload)


def test_schema_rejects_unresolved_claim_references_and_naive_dates() -> None:
    payload = _record().model_dump(mode="json")
    payload["candidates"][0]["evidence"][0]["claim_ids"] = ["missing"]
    with pytest.raises(ValidationError, match="evidence claim ids must exist"):
        TalentEvaluationRecord.model_validate(payload)
    payload = _record().model_dump(mode="json")
    payload["candidates"][0]["evidence"][0]["observed_at"] = "2026-07-01T12:00:00"
    with pytest.raises(ValidationError, match="timezone-aware"):
        TalentEvaluationRecord.model_validate(payload)


def test_evaluator_reports_safe_perfect_fixture_and_agreement() -> None:
    report = evaluate([_record()], [_submission()])
    assert report.relevance_ndcg_at_5 == 1.0
    assert report.policy_adjusted_ndcg_at_5 == 1.0
    assert report.qualified_recall_at_5_micro == 1.0
    assert report.qualified_recall_at_5_macro_eligible_cases == 1.0
    assert report.qualified_automatic_exclusion_rate == 0.0
    assert report.review_routing_recall == 1.0
    assert report.agreement.adjudication_rate == 0.0


def test_evaluator_excludes_no_qualified_cases_from_macro_recall() -> None:
    record = _record()
    labels = {key: value.model_copy(update={"hard_eligibility": "fail"}) for key, value in record.annotations.adjudicated_labels.items()}
    no_qualified = record.model_copy(update={"annotations": record.annotations.model_copy(update={"adjudicated_labels": labels})})
    report = evaluate([no_qualified], [_submission()])
    assert report.cases_with_no_qualified_candidates == 1
    assert report.qualified_recall_at_5_macro_eligible_cases is None
    assert report.qualified_recall_at_5_micro == 0.0


def test_slice_and_case_bootstrap_scaffolding() -> None:
    sliced = evaluate_by_slice([_record()], [_submission()], "job_family")
    assert sliced["engineering"].cases == 1
    assert sliced["engineering"].minimum_sample_warning is True
    intervals = bootstrap_confidence_intervals([_record()], [_submission()], samples=4, seed=1)
    assert intervals["relevance_ndcg_at_5"].lower == 1.0


def test_dataset_audit_reports_structural_coverage() -> None:
    report = audit_records([_record()])
    assert report.records == 1
    assert report.adjudication_counts == {"agreed": 1}
    assert report.missing_slices == {}
    assert report.invalid_record_digests == ("case-001",)


def test_record_digest_and_preregistered_manifest_are_verified() -> None:
    record = _record()
    record = record.model_copy(update={"provenance": record.provenance.model_copy(update={"record_digest": canonical_record_digest(record)})})
    assert audit_records([record]).invalid_record_digests == ()
    manifest = {"schema_version": "1.1", "manifest_version": "1", "dataset_digest": DIGEST, "declared_split": "pilot", "primary_metrics": ["policy_adjusted_ndcg_at_5"], "secondary_metrics": [], "threshold_profile": "calibration-only", "baseline_versions": {}, "model_artifact_digest": DIGEST, "policy_artifact_digest": DIGEST, "evaluation_code_commit": "abcdef0", "bootstrap_seed": 7, "excluded_case_ids": [], "exclusion_rules": [], "manifest_digest": ""}
    manifest["manifest_digest"] = canonical_digest({key: value for key, value in manifest.items() if key != "manifest_digest"})
    assert BenchmarkManifest.model_validate(manifest).manifest_version == "1"


def test_live_review_adapter_preserves_candidates_and_evaluates() -> None:
    review = apply_review_policy([
        CandidateJudgment(candidate_id="candidate-a", eligibility="eligible", evidence_consistency=.9, relevance_adjustment=0, recommended_action="shortlist"),
        CandidateJudgment(candidate_id="candidate-b", eligibility="eligible", evidence_consistency=.6, relevance_adjustment=0, recommended_action="hold_for_review"),
        CandidateJudgment(candidate_id="candidate-c", eligibility="ineligible", evidence_consistency=.2, relevance_adjustment=0, recommended_action="exclude_by_policy"),
    ], ["candidate-a", "candidate-b", "candidate-c"], [])
    submission = review_to_evaluation_submission(review, case_id="case-001", policy_version="policy-1", model_version="candidate-model-0", reproducibility=_submission().reproducibility)
    assert submission.ranked_candidate_ids == ("candidate-a", "candidate-b", "candidate-c")
    assert evaluate([_record()], [submission]).cases == 1
