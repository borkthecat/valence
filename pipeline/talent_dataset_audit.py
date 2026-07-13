"""Integrity checks for a collection of canonical Talent Integrity records."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from talent_evaluator import load_jsonl
from talent_schema import TalentEvaluationRecord


@dataclass(frozen=True, slots=True)
class DatasetAuditReport:
    records: int
    duplicate_case_ids: tuple[str, ...]
    duplicate_job_ids: tuple[str, ...]
    candidate_reused_across_splits: tuple[str, ...]
    evidence_hash_reused_across_splits: tuple[str, ...]
    mixed_policy_versions: tuple[str, ...]
    candidate_count_distribution: dict[str, int]
    adjudication_counts: dict[str, int]
    source_system_counts: dict[str, int]
    missing_slices: dict[str, int]
    reviewer_assignment_counts: dict[str, int]


def _duplicates(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(key for key, count in Counter(values).items() if count > 1))


def audit_records(records: list[TalentEvaluationRecord]) -> DatasetAuditReport:
    """Detect structural leakage and coverage gaps before benchmark evaluation.

    Textual near-duplicate and identity-linkage checks require controlled source
    access and are intentionally left to the secure collection environment.
    """
    candidate_splits: dict[str, set[str]] = defaultdict(set)
    evidence_splits: dict[str, set[str]] = defaultdict(set)
    reviewers: Counter[str] = Counter()
    source_systems: Counter[str] = Counter()
    missing = Counter()
    policy_versions: set[str] = set()
    candidate_counts: Counter[str] = Counter()
    adjudication: Counter[str] = Counter()
    for record in records:
        policy_versions.add(record.job.policy_version)
        candidate_counts[str(len(record.candidates))] += 1
        adjudication[record.annotations.adjudication_status] += 1
        for field in ("job_family", "seniority", "region", "language"):
            if not getattr(record.job, field): missing[field] += 1
        for reviewer in record.annotations.independent_reviews:
            reviewers[reviewer.reviewer_id] += 1
        for candidate in record.candidates:
            candidate_splits[candidate.candidate_id].add(record.split)
            source_systems[candidate.source_system] += 1
            for evidence in candidate.evidence:
                evidence_splits[evidence.content_hash].add(record.split)
    return DatasetAuditReport(
        records=len(records),
        duplicate_case_ids=_duplicates([record.case_id for record in records]),
        duplicate_job_ids=_duplicates([record.job.job_id for record in records]),
        candidate_reused_across_splits=tuple(sorted(key for key, splits in candidate_splits.items() if len(splits) > 1)),
        evidence_hash_reused_across_splits=tuple(sorted(key for key, splits in evidence_splits.items() if len(splits) > 1)),
        mixed_policy_versions=tuple(sorted(policy_versions)),
        candidate_count_distribution=dict(sorted(candidate_counts.items())),
        adjudication_counts=dict(sorted(adjudication.items())),
        source_system_counts=dict(sorted(source_systems.items())),
        missing_slices=dict(sorted(missing.items())),
        reviewer_assignment_counts=dict(sorted(reviewers.items())),
    )


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Audit a Talent Integrity JSONL dataset")
    parser.add_argument("records", type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(audit_records(load_jsonl(args.records))), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
