"""Canonical hashing and pre-registered benchmark manifest contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from talent_schema import SCHEMA_VERSION, TalentEvaluationRecord, TalentEvaluationSubmission, TalentModel


def canonical_digest(value: object, exclude: set[str] | None = None) -> str:
    """Hash canonical UTF-8 JSON; callers exclude self-referential digest fields."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude=exclude or set())
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_record_digest(record: TalentEvaluationRecord) -> str:
    payload = record.model_dump(mode="json")
    payload["provenance"].pop("record_digest", None)
    return canonical_digest(payload)


def canonical_submission_digest(submission: TalentEvaluationSubmission) -> str:
    return canonical_digest(submission)


class BenchmarkManifest(TalentModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    manifest_version: str = Field(min_length=1, max_length=64)
    dataset_digest: str = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    declared_split: Literal["pilot", "test", "shadow"]
    primary_metrics: tuple[str, ...] = Field(min_length=1, max_length=32)
    secondary_metrics: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    threshold_profile: str = Field(min_length=1, max_length=128)
    baseline_versions: dict[str, str] = Field(default_factory=dict, max_length=32)
    model_artifact_digest: str = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    policy_artifact_digest: str = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")
    evaluation_code_commit: str = Field(min_length=7, max_length=128)
    bootstrap_seed: int
    excluded_case_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=512)
    exclusion_rules: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    manifest_digest: str = Field(pattern=r"^sha256:[a-fA-F0-9]{64}$")

    @model_validator(mode="after")
    def digest_matches_contents(self) -> BenchmarkManifest:
        if self.manifest_digest != canonical_digest(self, {"manifest_digest"}):
            raise ValueError("manifest_digest does not match canonical manifest contents")
        return self
