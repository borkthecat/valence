"""Versioned canonical contracts for the Talent Integrity pilot.

These models deliberately do not adapt the legacy Stage 3–5 product-identification
schema. A domain adapter must map an enterprise source to this contract explicitly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SCHEMA_VERSION = "1.0"

EligibilityLabel = Literal["pass", "fail", "unknown"]
EvidenceSufficiency = Literal["sufficient", "partial", "insufficient"]
RiskLabel = Literal["none", "low", "medium", "high"]
SplitAssignment = Literal["pilot", "train", "validation", "test", "shadow"]
AdjudicationStatus = Literal["agreed", "adjudicated", "pending"]
WorkMode = Literal["on_site", "hybrid", "remote", "flexible", "unspecified"]


class TalentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class HardRequirement(TalentModel):
    requirement_id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1_024)
    required: bool = True
    evidence_required: bool = True


class JobContext(TalentModel):
    job_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    job_family: str | None = Field(default=None, max_length=128)
    department: str | None = Field(default=None, max_length=256)
    employment_type: str | None = Field(default=None, max_length=128)
    location: str | None = Field(default=None, max_length=256)
    region: str | None = Field(default=None, max_length=128)
    language: str | None = Field(default=None, max_length=64)
    work_mode: WorkMode = "unspecified"
    required_skills: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    preferred_skills: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    minimum_experience_years: float | None = Field(default=None, ge=0, le=80)
    seniority: str | None = Field(default=None, max_length=128)
    certifications: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    education_requirements: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    work_authorization_requirements: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    compensation_constraints: str | None = Field(default=None, max_length=512)
    hard_requirements: tuple[HardRequirement, ...] = Field(default_factory=tuple, max_length=32)
    soft_preferences: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    policy_version: str = Field(min_length=1, max_length=128)
    jurisdiction: str = Field(min_length=2, max_length=64)


class EvidenceItem(TalentModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_type: Literal["resume", "application", "portfolio", "reference", "certification", "external_verification", "other"]
    source_uri: HttpUrl | None = None
    trust_level: Literal["verified", "unverified", "self_reported", "third_party", "unknown"]
    content_hash: str = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    observed_at: str = Field(min_length=1, max_length=64)
    verification_status: Literal["verified", "unverified", "conflicting", "unavailable"]
    claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)


class WorkHistoryItem(TalentModel):
    organization: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=256)
    skills: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    started_on: str | None = Field(default=None, max_length=16)
    ended_on: str | None = Field(default=None, max_length=16)
    current: bool = False


class CandidateProfile(TalentModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    claimed_skills: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    work_history: tuple[WorkHistoryItem, ...] = Field(default_factory=tuple, max_length=64)
    experience_years: float | None = Field(default=None, ge=0, le=80)
    most_recent_relevant_experience_on: str | None = Field(default=None, max_length=16)
    education: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    certifications: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    location: str | None = Field(default=None, max_length=256)
    work_authorization: str | None = Field(default=None, max_length=256)
    availability: str | None = Field(default=None, max_length=256)
    evidence: tuple[EvidenceItem, ...] = Field(default_factory=tuple, max_length=64)
    profile_completeness: float = Field(ge=0.0, le=1.0)
    verified_claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    unverified_claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    fraud_or_inconsistency_signals: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    source_system: str = Field(min_length=1, max_length=128)


class CandidateAnnotation(TalentModel):
    hard_eligibility: EligibilityLabel
    graded_relevance: int = Field(ge=0, le=3)
    evidence_sufficiency: EvidenceSufficiency
    fraud_or_inconsistency_risk: RiskLabel
    human_review_required: bool
    reviewer_explanation: str = Field(min_length=1, max_length=4_096)
    confidence: float = Field(ge=0, le=1)
    disagreement_reason: str | None = Field(default=None, max_length=1_024)


class Annotations(TalentModel):
    candidate_annotations: dict[str, CandidateAnnotation]
    reviewer_ids: tuple[str, ...] = Field(min_length=2, max_length=3)
    adjudication_status: AdjudicationStatus
    annotation_version: str = Field(min_length=1, max_length=64)


class TalentEvaluationRecord(TalentModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=128)
    dataset_version: str = Field(min_length=1, max_length=128)
    split: SplitAssignment
    job: JobContext
    candidates: tuple[CandidateProfile, ...] = Field(min_length=1, max_length=50)
    annotations: Annotations
    provenance: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def annotation_candidates_match_case(self) -> TalentEvaluationRecord:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique within a case")
        if set(self.annotations.candidate_annotations) != set(ids):
            raise ValueError("candidate annotations must cover every candidate exactly once")
        return self


class SystemCandidateAssessment(TalentModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    eligibility: EligibilityLabel
    evidence_sufficiency: EvidenceSufficiency
    risk: RiskLabel
    uncertainty: float = Field(ge=0, le=1)
    human_review_required: bool
    shortlist_eligible: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)


class TalentEvaluationSubmission(TalentModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    ranked_candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    assessments: tuple[SystemCandidateAssessment, ...] = Field(min_length=1, max_length=50)

    @field_validator("ranked_candidate_ids")
    @classmethod
    def unique_ranking(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("ranked candidate ids must be unique")
        return value

    @model_validator(mode="after")
    def assessment_candidates_are_unique(self) -> TalentEvaluationSubmission:
        ids = [assessment.candidate_id for assessment in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("assessment candidate ids must be unique")
        return self
