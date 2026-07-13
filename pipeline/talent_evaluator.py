"""Offline evaluator for independently adjudicated Talent Integrity records."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from talent_schema import TalentEvaluationRecord, TalentEvaluationSubmission


@dataclass(frozen=True, slots=True)
class TalentEvaluationReport:
    cases: int
    ndcg_at_5: float
    qualified_recall_at_5: float
    pairwise_preference_accuracy: float
    top1_agreement: float
    hard_eligibility_violation_rate: float
    unsupported_evidence_promotion_rate: float
    human_review_routing_rate: float
    incorrect_automatic_exclusion_rate: float
    mean_uncertainty: float


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def evaluate(records: list[TalentEvaluationRecord], submissions: list[TalentEvaluationSubmission]) -> TalentEvaluationReport:
    if not records:
        raise ValueError("evaluation records are empty")
    if len({record.case_id for record in records}) != len(records):
        raise ValueError("evaluation record case ids must be unique")
    if len({submission.case_id for submission in submissions}) != len(submissions):
        raise ValueError("submission case ids must be unique")
    by_case = {submission.case_id: submission for submission in submissions}
    if set(by_case) != {record.case_id for record in records}:
        raise ValueError("submissions must cover every evaluation case exactly once")

    ndcg = recall = top1 = pairwise_correct = pairwise_total = 0.0
    eligibility_violations = unsupported_promotions = review_count = auto_exclusions = candidates = 0
    uncertainty_sum = 0.0
    for record in records:
        if record.annotations.adjudication_status not in ("agreed", "adjudicated"):
            raise ValueError("only agreed or adjudicated records may be evaluated")
        submission = by_case[record.case_id]
        ids = {candidate.candidate_id for candidate in record.candidates}
        if set(submission.ranked_candidate_ids) != ids:
            raise ValueError(f"ranking for {record.case_id} must include every candidate exactly once")
        assessments = {assessment.candidate_id: assessment for assessment in submission.assessments}
        if set(assessments) != ids:
            raise ValueError(f"assessments for {record.case_id} must include every candidate exactly once")
        labels = record.annotations.candidate_annotations
        ranked = list(submission.ranked_candidate_ids)
        grades = [labels[candidate_id].graded_relevance for candidate_id in ranked[:5]]
        ideal = _dcg(sorted((item.graded_relevance for item in labels.values()), reverse=True)[:5])
        ndcg += _dcg(grades) / ideal if ideal else 0.0
        qualified = {candidate_id for candidate_id, label in labels.items() if label.hard_eligibility == "pass" and label.graded_relevance >= 2}
        recall += len(set(ranked[:5]) & qualified) / len(qualified) if qualified else 1.0
        best = max(label.graded_relevance for label in labels.values())
        top1 += int(labels[ranked[0]].graded_relevance == best)
        positions = {candidate_id: index for index, candidate_id in enumerate(ranked)}
        for left, left_label in labels.items():
            for right, right_label in labels.items():
                if left < right and left_label.graded_relevance != right_label.graded_relevance:
                    pairwise_total += 1
                    preferred, other = (left, right) if left_label.graded_relevance > right_label.graded_relevance else (right, left)
                    pairwise_correct += int(positions[preferred] < positions[other])
        for candidate_id, label in labels.items():
            assessment = assessments[candidate_id]
            candidates += 1
            uncertainty_sum += assessment.uncertainty
            review_count += int(assessment.human_review_required)
            eligibility_violations += int(label.hard_eligibility == "fail" and assessment.shortlist_eligible)
            unsupported_promotions += int(label.evidence_sufficiency == "insufficient" and assessment.shortlist_eligible)
            auto_exclusions += int(label.hard_eligibility == "pass" and not assessment.shortlist_eligible and not assessment.human_review_required)
    total = len(records)
    return TalentEvaluationReport(
        cases=total,
        ndcg_at_5=ndcg / total,
        qualified_recall_at_5=recall / total,
        pairwise_preference_accuracy=pairwise_correct / pairwise_total if pairwise_total else 0.0,
        top1_agreement=top1 / total,
        hard_eligibility_violation_rate=eligibility_violations / candidates,
        unsupported_evidence_promotion_rate=unsupported_promotions / candidates,
        human_review_routing_rate=review_count / candidates,
        incorrect_automatic_exclusion_rate=auto_exclusions / candidates,
        mean_uncertainty=uncertainty_sum / candidates,
    )


def evaluate_by_slice(
    records: list[TalentEvaluationRecord],
    submissions: list[TalentEvaluationSubmission],
    slice_name: str,
) -> dict[str, TalentEvaluationReport]:
    """Report pilot metrics by a predeclared, non-protected dataset slice."""
    allowed = {"job_family", "seniority", "region", "language", "profile_completeness"}
    if slice_name not in allowed:
        raise ValueError(f"unsupported slice {slice_name!r}; choose one of {sorted(allowed)}")
    submissions_by_case = {submission.case_id: submission for submission in submissions}
    groups: dict[str, list[TalentEvaluationRecord]] = {}
    for record in records:
        if slice_name == "profile_completeness":
            mean_completeness = sum(candidate.profile_completeness for candidate in record.candidates) / len(record.candidates)
            value = "sparse" if mean_completeness < 0.5 else "mixed" if mean_completeness < 0.8 else "rich"
        else:
            value = getattr(record.job, slice_name) or "unspecified"
        groups.setdefault(value, []).append(record)
    return {
        value: evaluate(group, [submissions_by_case[record.case_id] for record in group])
        for value, group in sorted(groups.items())
    }


def load_jsonl(path: Path) -> list[TalentEvaluationRecord]:
    return [TalentEvaluationRecord.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate Talent Integrity pilot submissions")
    parser.add_argument("records", type=Path)
    parser.add_argument("submissions", type=Path)
    args = parser.parse_args()
    submissions = [TalentEvaluationSubmission.model_validate(json.loads(line)) for line in args.submissions.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(asdict(evaluate(load_jsonl(args.records), submissions)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
