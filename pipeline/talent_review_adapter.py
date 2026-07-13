"""Deterministic adapter from the live advisory review to evaluation submissions."""

from __future__ import annotations

from stage5_cognitive_verifier import StructuredReview
from talent_schema import ReproducibilityMetadata, SystemCandidateAssessment, TalentEvaluationSubmission


def review_to_evaluation_submission(
    review: StructuredReview,
    *,
    case_id: str,
    policy_version: str,
    model_version: str,
    reproducibility: ReproducibilityMetadata,
    review_uncertainty_threshold: float = 0.5,
) -> TalentEvaluationSubmission:
    """Map only explicit live fields; unavailable values are never inferred."""
    assessments: list[SystemCandidateAssessment] = []
    for candidate in review.candidates:
        finding, outcome = candidate.model_assessment, candidate.policy_outcome
        eligibility = {"eligible": "pass", "ineligible": "fail", "unknown": "unknown"}[finding.eligibility]
        evidence = "sufficient" if finding.evidence_consistency >= .75 else "partial" if finding.evidence_consistency >= .4 else "insufficient"
        risk = "high" if finding.risk_findings else "none"
        uncertainty = max(1 - finding.evidence_consistency, review_uncertainty_threshold if outcome.human_review_required else 0.0)
        reason_codes = tuple(code for code in outcome.reason_codes if code in {"RISK_PROFILE_INCONSISTENCY", "RISK_UNTRUSTED_PROVENANCE", "UNCERTAINTY_MISSING_REQUIRED_EVIDENCE", "POLICY_HARD_REQUIREMENT_FAILED"})
        if len(reason_codes) != len(outcome.reason_codes):
            raise ValueError("live review emitted an unregistered reason code")
        assessments.append(SystemCandidateAssessment(candidate_id=candidate.candidate_id, eligibility=eligibility, evidence_sufficiency=evidence, risk=risk, uncertainty=uncertainty, human_review_required=outcome.human_review_required, shortlist_eligible=outcome.shortlist_eligible, reason_codes=reason_codes))
    shortlist = [candidate_id for candidate_id in review.recommended_shortlist]
    remaining = [candidate.candidate_id for candidate in review.candidates if candidate.candidate_id not in shortlist]
    return TalentEvaluationSubmission(case_id=case_id, policy_version=policy_version, model_version=model_version, ranked_candidate_ids=tuple(shortlist + remaining), assessments=tuple(assessments), reproducibility=reproducibility, review_uncertainty_threshold=review_uncertainty_threshold)
