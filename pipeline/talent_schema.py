"""Versioned canonical contracts for independently reviewed Talent Integrity data.

These models deliberately do not adapt the legacy Stage 3--5
product-identification schema. A reviewed domain adapter is required.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SCHEMA_VERSION = "1.1"
Digest = str
EligibilityLabel = Literal["pass", "fail", "unknown"]
EvidenceSufficiency = Literal["sufficient", "partial", "insufficient"]
RiskLabel = Literal["none", "low", "medium", "high"]
SplitAssignment = Literal["pilot", "train", "validation", "test", "shadow"]
AdjudicationStatus = Literal["agreed", "adjudicated", "pending"]
WorkMode = Literal["on_site", "hybrid", "remote", "flexible", "unspecified"]
ReasonCode = Literal[
    "RISK_PROFILE_INCONSISTENCY",
    "RISK_UNTRUSTED_PROVENANCE",
    "UNCERTAINTY_MISSING_REQUIRED_EVIDENCE",
    "POLICY_HARD_REQUIREMENT_FAILED",
]


class TalentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PartialDate(TalentModel):
    """A calendar date with declared precision; never an overloaded free string."""

    year: int = Field(ge=1900, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)
    precision: Literal["year", "month", "day"]

    @model_validator(mode="after")
    def precision_matches_components(self) -> PartialDate:
        if self.precision == "year" and (self.month is not None or self.day is not None):
            raise ValueError("year precision cannot include month or day")
        if self.precision == "month" and (self.month is None or self.day is not None):
            raise ValueError("month precision requires month and cannot include day")
        if self.precision == "day":
            if self.month is None or self.day is None:
                raise ValueError("day precision requires month and day")
            date(self.year, self.month, self.day)
        return self

    def earliest(self) -> date:
        return date(self.year, self.month or 1, self.day or 1)


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
    content_hash: Digest = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    observed_at: datetime
    verification_status: Literal["verified", "unverified", "conflicting", "unavailable"]
    claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class CandidateClaim(TalentModel):
    claim_id: str = Field(min_length=1, max_length=128)
    claim_type: Literal["skill", "employment", "education", "certification", "work_authorization", "location", "availability", "other"]
    normalized_value: str = Field(min_length=1, max_length=1_024)
    raw_value_hash: Digest | None = Field(default=None, pattern=r"^sha256:[a-fA-F0-9]{64}$")
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    verification_status: Literal["verified", "partially_verified", "unverified", "conflicting", "unavailable"]


class WorkHistoryItem(TalentModel):
    organization: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=256)
    skills: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    started_on: PartialDate | None = None
    ended_on: PartialDate | None = None
    current: bool = False

    @model_validator(mode="after")
    def dates_are_coherent(self) -> WorkHistoryItem:
        today = date.today()
        if self.started_on and self.started_on.earliest() > today:
            raise ValueError("future work-history start dates are not allowed")
        if self.ended_on and self.ended_on.earliest() > today:
            raise ValueError("future work-history end dates are not allowed")
        if self.current and self.ended_on is not None:
            raise ValueError("current work history must not have an end date")
        if self.started_on and self.ended_on and self.ended_on.earliest() < self.started_on.earliest():
            raise ValueError("work-history end date cannot precede start date")
        return self


class CandidateProfile(TalentModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    claimed_skills: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    work_history: tuple[WorkHistoryItem, ...] = Field(default_factory=tuple, max_length=64)
    experience_years: float | None = Field(default=None, ge=0, le=80)
    most_recent_relevant_experience_on: PartialDate | None = None
    education: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    certifications: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    location: str | None = Field(default=None, max_length=256)
    work_authorization: str | None = Field(default=None, max_length=256)
    availability: str | None = Field(default=None, max_length=256)
    evidence: tuple[EvidenceItem, ...] = Field(default_factory=tuple, max_length=64)
    claims: tuple[CandidateClaim, ...] = Field(default_factory=tuple, max_length=128)
    profile_completeness: float = Field(ge=0.0, le=1.0)
    verified_claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    unverified_claim_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    fraud_or_inconsistency_signals: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    source_system: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def evidence_graph_is_consistent(self) -> CandidateProfile:
        evidence_ids = [item.evidence_id for item in self.evidence]
        claim_ids = [item.claim_id for item in self.claims]
        if len(evidence_ids) != len(set(evidence_ids)) or len(claim_ids) != len(set(claim_ids)):
            raise ValueError("evidence ids and claim ids must be unique per candidate")
        evidence_set, claim_set = set(evidence_ids), set(claim_ids)
        if not set(self.verified_claim_ids).isdisjoint(self.unverified_claim_ids):
            raise ValueError("verified and unverified claim ids must not overlap")
        if not (set(self.verified_claim_ids) | set(self.unverified_claim_ids)) <= claim_set:
            raise ValueError("verified and unverified claim ids must exist")
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        for evidence in self.evidence:
            if not set(evidence.claim_ids) <= claim_set:
                raise ValueError("evidence claim ids must exist")
        for claim in self.claims:
            if not set(claim.evidence_ids) <= evidence_set:
                raise ValueError("claim evidence ids must exist")
            if claim.claim_id in self.verified_claim_ids:
                if claim.verification_status not in ("verified", "partially_verified"):
                    raise ValueError("verified claims need a qualifying verification status")
                if not any(evidence_by_id[item].verification_status == "verified" for item in claim.evidence_ids):
                    raise ValueError("verified claims require verified evidence")
        return self


class CandidateAnnotation(TalentModel):
    """Resolved adjudicated label used for system-performance evaluation."""

    hard_eligibility: EligibilityLabel
    graded_relevance: int = Field(ge=0, le=3)
    evidence_sufficiency: EvidenceSufficiency
    fraud_or_inconsistency_risk: RiskLabel
    human_review_required: bool
    explanation: str = Field(min_length=1, max_length=4_096)
    confidence: float = Field(ge=0, le=1)


class ReviewerCandidateAnnotation(CandidateAnnotation):
    reviewer_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    completed_at: datetime
    rubric_version: str = Field(min_length=1, max_length=64)

    @field_validator("completed_at")
    @classmethod
    def completed_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        return value


class ReviewerCaseAnnotation(TalentModel):
    reviewer_id: str = Field(min_length=1, max_length=128)
    candidate_annotations: tuple[ReviewerCandidateAnnotation, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def review_belongs_to_one_reviewer(self) -> ReviewerCaseAnnotation:
        if any(item.reviewer_id != self.reviewer_id for item in self.candidate_annotations):
            raise ValueError("reviewer candidate annotations must belong to the case reviewer")
        ids = [item.candidate_id for item in self.candidate_annotations]
        if len(ids) != len(set(ids)):
            raise ValueError("each reviewer may annotate a candidate once")
        return self


class CaseAnnotations(TalentModel):
    independent_reviews: tuple[ReviewerCaseAnnotation, ...] = Field(min_length=2, max_length=3)
    adjudicated_labels: dict[str, CandidateAnnotation] | None = None
    adjudication_status: AdjudicationStatus
    adjudicator_id: str | None = Field(default=None, max_length=128)
    adjudication_reason: str | None = Field(default=None, max_length=4_096)
    adjudicated_at: datetime | None = None

    @model_validator(mode="after")
    def adjudication_fields_are_consistent(self) -> CaseAnnotations:
        ids = [review.reviewer_id for review in self.independent_reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("independent reviewer ids must be unique")
        if self.adjudication_status == "pending":
            if self.adjudicated_labels is not None:
                raise ValueError("pending cases cannot contain adjudicated labels")
        else:
            if self.adjudicated_labels is None:
                raise ValueError("agreed or adjudicated cases require adjudicated labels")
        if self.adjudication_status == "adjudicated":
            if not (self.adjudicator_id and self.adjudication_reason and self.adjudicated_at):
                raise ValueError("adjudicated cases require adjudicator id, reason, and timestamp")
        elif any((self.adjudicator_id, self.adjudication_reason, self.adjudicated_at)):
            raise ValueError("only adjudicated cases may include adjudicator fields")
        if self.adjudicated_at and (self.adjudicated_at.tzinfo is None or self.adjudicated_at.utcoffset() is None):
            raise ValueError("adjudicated_at must be timezone-aware")
        return self


class DatasetProvenance(TalentModel):
    source_system: str = Field(min_length=1, max_length=128)
    export_id: str = Field(min_length=1, max_length=256)
    export_timestamp: datetime
    collector_version: str = Field(min_length=1, max_length=128)
    transformation_version: str = Field(min_length=1, max_length=128)
    source_policy_version: str = Field(min_length=1, max_length=128)
    deidentification_version: str = Field(min_length=1, max_length=128)
    record_digest: Digest = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    source_record_digest: Digest | None = Field(default=None, pattern=r"^sha256:[a-fA-F0-9]{64}$")
    consent_basis: str | None = Field(default=None, max_length=256)
    tenant_pseudonym: str | None = Field(default=None, max_length=128)
    retention_expires_at: datetime | None = None
    data_residency: str | None = Field(default=None, max_length=64)
    source_schema_version: str | None = Field(default=None, max_length=128)

    @field_validator("export_timestamp", "retention_expires_at")
    @classmethod
    def timestamps_are_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("provenance timestamps must be timezone-aware")
        return value


class TalentEvaluationRecord(TalentModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=128)
    dataset_version: str = Field(min_length=1, max_length=128)
    split: SplitAssignment
    job: JobContext
    candidates: tuple[CandidateProfile, ...] = Field(min_length=1, max_length=50)
    annotations: CaseAnnotations
    provenance: DatasetProvenance

    @model_validator(mode="after")
    def annotations_and_observations_match_case(self) -> TalentEvaluationRecord:
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique within a case")
        candidate_ids = set(ids)
        for review in self.annotations.independent_reviews:
            if {item.candidate_id for item in review.candidate_annotations} != candidate_ids:
                raise ValueError("each independent review must cover every candidate exactly once")
        if self.annotations.adjudicated_labels is not None and set(self.annotations.adjudicated_labels) != candidate_ids:
            raise ValueError("adjudicated labels must cover every candidate exactly once")
        for candidate in self.candidates:
            for evidence in candidate.evidence:
                if evidence.observed_at > self.provenance.export_timestamp:
                    raise ValueError("evidence observations cannot be later than dataset export")
        return self


class SystemCandidateAssessment(TalentModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    eligibility: EligibilityLabel
    evidence_sufficiency: EvidenceSufficiency
    risk: RiskLabel
    uncertainty: float = Field(ge=0, le=1)
    human_review_required: bool
    shortlist_eligible: bool
    reason_codes: tuple[ReasonCode, ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def policy_outcome_is_safe(self) -> SystemCandidateAssessment:
        if self.eligibility == "fail" and self.shortlist_eligible:
            raise ValueError("failed eligibility cannot be shortlist eligible")
        if self.eligibility == "unknown" and not self.human_review_required:
            raise ValueError("unknown eligibility requires human review")
        if self.risk == "high" and not self.human_review_required:
            raise ValueError("high risk requires human review")
        if self.evidence_sufficiency == "insufficient" and self.shortlist_eligible and not self.human_review_required:
            raise ValueError("insufficient evidence cannot be shortlisted without review")
        return self


class ReproducibilityMetadata(TalentModel):
    run_id: str = Field(min_length=1, max_length=128)
    submitted_at: datetime
    evaluator_version: str = Field(min_length=1, max_length=128)
    model_artifact_digest: Digest = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    policy_artifact_digest: Digest = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    configuration_digest: Digest = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    inference_provider: str = Field(min_length=1, max_length=128)
    execution_environment: str = Field(min_length=1, max_length=256)
    random_seed: int | None = None

    @field_validator("submitted_at")
    @classmethod
    def submitted_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("submitted_at must be timezone-aware")
        return value


class TalentEvaluationSubmission(TalentModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    ranked_candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=50)
    assessments: tuple[SystemCandidateAssessment, ...] = Field(min_length=1, max_length=50)
    reproducibility: ReproducibilityMetadata
    review_uncertainty_threshold: float = Field(default=0.5, ge=0, le=1)

    @model_validator(mode="after")
    def ranking_and_assessments_match(self) -> TalentEvaluationSubmission:
        ranked = set(self.ranked_candidate_ids)
        assessment_ids = [item.candidate_id for item in self.assessments]
        if len(ranked) != len(self.ranked_candidate_ids):
            raise ValueError("ranked candidate ids must be unique")
        if len(assessment_ids) != len(set(assessment_ids)):
            raise ValueError("assessment candidate ids must be unique")
        if ranked != set(assessment_ids):
            raise ValueError("ranked candidates and assessed candidates must match exactly")
        if any(item.uncertainty >= self.review_uncertainty_threshold and not item.human_review_required for item in self.assessments):
            raise ValueError("assessments at or above the uncertainty threshold require human review")
        return self
