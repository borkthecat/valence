"""Offline evaluation for independently reviewed Talent Integrity records.

Metrics are diagnostic scaffolding. No acceptance threshold is encoded here.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Protocol

from talent_schema import CandidateAnnotation, TalentEvaluationRecord, TalentEvaluationSubmission


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float
    confidence_level: float = 0.95
    method: str = "case_bootstrap"


@dataclass(frozen=True, slots=True)
class AgreementMetrics:
    hard_eligibility_cohen_kappa: float | None
    evidence_sufficiency_cohen_kappa: float | None
    review_required_cohen_kappa: float | None
    relevance_weighted_kappa: float | None
    risk_weighted_kappa: float | None
    krippendorff_alpha_nominal: float | None
    rank_spearman_correlation: float | None
    rank_kendall_tau_b: float | None
    top5_overlap: float | None
    adjudication_rate: float
    mean_reviewer_confidence_difference: float | None


@dataclass(frozen=True, slots=True)
class TalentEvaluationReport:
    cases: int
    candidates: int
    cases_with_no_qualified_candidates: int
    applicable_recall_cases: int
    relevance_ndcg_at_5: float
    policy_adjusted_ndcg_at_5: float
    qualified_recall_at_5_micro: float
    qualified_recall_at_5_macro_eligible_cases: float | None
    relevance_pairwise_accuracy: float
    eligibility_aware_pairwise_accuracy: float
    hard_pair_accuracy: float
    top1_agreement: float
    top5_overlap: float
    hard_eligibility_shortlist_violation_rate: float
    unsupported_evidence_promotion_rate: float
    qualified_automatic_exclusion_rate: float
    eligible_automatic_exclusion_rate: float
    unknown_eligibility_automatic_decision_rate: float
    high_risk_automatic_advancement_rate: float
    review_routing_precision: float | None
    review_routing_recall: float | None
    review_routing_f1: float | None
    review_false_positive_rate: float | None
    review_miss_rate: float | None
    review_workload_rate: float
    mean_uncertainty: float
    mean_uncertainty_on_correct: float | None
    mean_uncertainty_on_incorrect: float | None
    agreement: AgreementMetrics
    confidence_intervals: dict[str, ConfidenceInterval] = field(default_factory=dict)
    minimum_sample_warning: bool = False


class RankingBaseline(Protocol):
    """Interface for pre-registered non-model ranking baselines."""

    name: str

    def rank(self, record: TalentEvaluationRecord) -> tuple[str, ...]: ...


class HardEligibilityLexicalBaseline:
    """Deployable lexical baseline: candidate fields only, never human labels."""

    name = "lexical_skill_overlap"

    def rank(self, record: TalentEvaluationRecord) -> tuple[str, ...]:
        required = {skill.casefold() for skill in record.job.required_skills}
        def key(candidate: object) -> tuple[int, int, str]:
            profile = candidate
            skills = {skill.casefold() for skill in profile.claimed_skills}
            preferred = {skill.casefold() for skill in record.job.preferred_skills}
            return (-len(required & skills), -len(preferred & skills), profile.candidate_id)
        return tuple(item.candidate_id for item in sorted(record.candidates, key=key))


class OracleHardEligibilityLexicalBaseline(HardEligibilityLexicalBaseline):
    """Diagnostic upper bound only; this baseline intentionally reads resolved labels."""

    name = "oracle_hard_eligibility_then_skill_overlap"

    def rank(self, record: TalentEvaluationRecord) -> tuple[str, ...]:
        labels = _labels(record)
        lexical = super().rank(record)
        return tuple(sorted(lexical, key=lambda candidate_id: (labels[candidate_id].hard_eligibility != "pass", lexical.index(candidate_id))))


def _labels(record: TalentEvaluationRecord) -> dict[str, CandidateAnnotation]:
    if record.annotations.adjudication_status not in ("agreed", "adjudicated") or record.annotations.adjudicated_labels is None:
        raise ValueError("only agreed or adjudicated records with resolved labels may be evaluated")
    return record.annotations.adjudicated_labels


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


RISK_ORDER = ["none", "low", "medium", "high"]
RELEVANCE_ORDER = [0, 1, 2, 3]
EVIDENCE_ORDER = ["insufficient", "partial", "sufficient"]


def _kappa(left: list[object], right: list[object], weighted: bool = False, order: list[object] | None = None, quadratic: bool = True) -> float | None:
    if not left or len(left) != len(right):
        return None
    categories = order or sorted(set(left) | set(right), key=str)
    if not set(left) | set(right) <= set(categories):
        raise ValueError("kappa category order does not cover values")
    def weight(a: object, b: object) -> float:
        if not weighted: return float(a == b)
        distance = abs(categories.index(a) - categories.index(b)) / max(1, len(categories) - 1)
        return 1 - (distance**2 if quadratic else distance)
    observed = mean(weight(a, b) for a, b in zip(left, right))
    left_counts = {value: left.count(value) / len(left) for value in categories}
    right_counts = {value: right.count(value) / len(right) for value in categories}
    expected = sum(left_counts[a] * right_counts[b] * weight(a, b) for a in categories for b in categories)
    return 1.0 if expected == 1.0 and observed == 1.0 else (observed - expected) / (1 - expected) if expected != 1 else 0.0


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    mean_left, mean_right = mean(left), mean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
    return numerator / denominator if denominator else None


def _average_descending_ranks(values: dict[str, int]) -> dict[str, float]:
    """Tie-aware ranks: equal values get the average of their occupied ranks."""
    result: dict[str, float] = {}
    ordered = sorted(values, key=lambda item: (-values[item], item))
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[index]]: end += 1
        average = ((index + 1) + end) / 2
        for item in ordered[index:end]: result[item] = average
        index = end
    return result


def _kendall_tau_b(left: list[float], right: list[float]) -> float | None:
    concordant = discordant = left_ties = right_ties = 0
    for i, j in combinations(range(len(left)), 2):
        a, b = left[i] - left[j], right[i] - right[j]
        if a == b == 0: continue
        if a == 0: left_ties += 1
        elif b == 0: right_ties += 1
        elif (a > 0) == (b > 0): concordant += 1
        else: discordant += 1
    denominator = math.sqrt((concordant + discordant + left_ties) * (concordant + discordant + right_ties))
    return (concordant - discordant) / denominator if denominator else None


def _agreement(records: list[TalentEvaluationRecord]) -> AgreementMetrics:
    eligibility: tuple[list[object], list[object]] = ([], [])
    evidence: tuple[list[object], list[object]] = ([], [])
    review: tuple[list[object], list[object]] = ([], [])
    relevance: tuple[list[object], list[object]] = ([], [])
    risk: tuple[list[object], list[object]] = ([], [])
    confidence_diffs: list[float] = []
    rank_correlations: list[float] = []; kendall_correlations: list[float] = []
    overlaps: list[float] = []
    all_nominal_items: list[list[object]] = []
    for record in records:
        first, second = record.annotations.independent_reviews[:2]
        first_by_id = {item.candidate_id: item for item in first.candidate_annotations}
        second_by_id = {item.candidate_id: item for item in second.candidate_annotations}
        ids = sorted(first_by_id)
        for candidate_id in ids:
            a, b = first_by_id[candidate_id], second_by_id[candidate_id]
            eligibility[0].append(a.hard_eligibility); eligibility[1].append(b.hard_eligibility)
            evidence[0].append(a.evidence_sufficiency); evidence[1].append(b.evidence_sufficiency)
            review[0].append(a.human_review_required); review[1].append(b.human_review_required)
            relevance[0].append(a.graded_relevance); relevance[1].append(b.graded_relevance)
            risk[0].append(a.fraud_or_inconsistency_risk); risk[1].append(b.fraud_or_inconsistency_risk)
            confidence_diffs.append(abs(a.confidence - b.confidence))
            all_nominal_items.append([item.hard_eligibility for reviewer in record.annotations.independent_reviews for item in reviewer.candidate_annotations if item.candidate_id == candidate_id])
        left_pos = _average_descending_ranks({item: first_by_id[item].graded_relevance for item in ids})
        right_pos = _average_descending_ranks({item: second_by_id[item].graded_relevance for item in ids})
        left_values, right_values = [left_pos[item] for item in ids], [right_pos[item] for item in ids]
        correlation = _spearman(left_values, right_values)
        if correlation is not None: rank_correlations.append(correlation)
        kendall = _kendall_tau_b(left_values, right_values)
        if kendall is not None: kendall_correlations.append(kendall)
        left_top = {item for item in ids if left_pos[item] <= 5}; right_top = {item for item in ids if right_pos[item] <= 5}
        overlaps.append(len(left_top & right_top) / min(5, len(ids)))
    observed_pairs = [(a, b) for values in all_nominal_items for a, b in combinations(values, 2)]
    all_values = [value for values in all_nominal_items for value in values]
    observed_disagreement = mean(float(a != b) for a, b in observed_pairs) if observed_pairs else None
    expected_disagreement = mean(float(a != b) for a, b in combinations(all_values, 2)) if len(all_values) > 1 else None
    alpha = None if observed_disagreement is None or expected_disagreement in (None, 0) else 1 - observed_disagreement / expected_disagreement
    return AgreementMetrics(_kappa(*eligibility), _kappa(*evidence), _kappa(*review), _kappa(*relevance, weighted=True, order=RELEVANCE_ORDER), _kappa(*risk, weighted=True, order=RISK_ORDER), alpha, mean(rank_correlations) if rank_correlations else None, mean(kendall_correlations) if kendall_correlations else None, mean(overlaps) if overlaps else None, sum(record.annotations.adjudication_status == "adjudicated" for record in records) / len(records), mean(confidence_diffs) if confidence_diffs else None)


def evaluate(records: list[TalentEvaluationRecord], submissions: list[TalentEvaluationSubmission]) -> TalentEvaluationReport:
    if not records: raise ValueError("evaluation records are empty")
    if len({record.case_id for record in records}) != len(records) or len({item.case_id for item in submissions}) != len(submissions): raise ValueError("case ids must be unique")
    by_case = {item.case_id: item for item in submissions}
    if set(by_case) != {record.case_id for record in records}: raise ValueError("submissions must cover every evaluation case exactly once")
    rel_ndcg = policy_ndcg = macro_recall_sum = top1 = top5 = pair_correct = pair_total = eligible_pair_correct = eligible_pair_total = hard_correct = hard_total = 0.0
    qualified_found = qualified_total = no_qualified = applicable = candidates = 0
    hard_violation = unsupported = qualified_exclusion = eligible_exclusion = unknown_auto = high_risk_auto = review_tp = review_fp = review_fn = review_tn = 0
    uncertainties: list[float] = []; correct_uncertainties: list[float] = []; incorrect_uncertainties: list[float] = []
    for record in records:
        labels = _labels(record); submission = by_case[record.case_id]; ids = set(labels)
        if set(submission.ranked_candidate_ids) != ids: raise ValueError(f"ranking for {record.case_id} must include every candidate exactly once")
        assessments = {item.candidate_id: item for item in submission.assessments}
        ranked = list(submission.ranked_candidate_ids)
        grades = [labels[item].graded_relevance for item in ranked[:5]]
        ideal = _dcg(sorted((item.graded_relevance for item in labels.values()), reverse=True)[:5])
        rel_ndcg += _dcg(grades) / ideal if ideal else 0.0
        policy_grades = [labels[item].graded_relevance if labels[item].hard_eligibility == "pass" else 0 for item in ranked[:5]]
        policy_ideal = _dcg(sorted((item.graded_relevance if item.hard_eligibility == "pass" else 0 for item in labels.values()), reverse=True)[:5])
        policy_ndcg += _dcg(policy_grades) / policy_ideal if policy_ideal else 0.0
        qualified = {item for item, label in labels.items() if label.hard_eligibility == "pass" and label.graded_relevance >= 2}
        if qualified:
            found = len(set(ranked[:5]) & qualified); qualified_found += found; qualified_total += len(qualified); macro_recall_sum += found / len(qualified); applicable += 1
        else: no_qualified += 1
        top1 += int(labels[ranked[0]].graded_relevance == max(item.graded_relevance for item in labels.values()))
        top5 += len(set(ranked[:5]) & set(sorted(labels, key=lambda item: (-labels[item].graded_relevance, item))[:5])) / min(5, len(labels))
        positions = {item: index for index, item in enumerate(ranked)}
        for left, right in combinations(labels, 2):
            left_label, right_label = labels[left], labels[right]
            if left_label.graded_relevance != right_label.graded_relevance:
                preferred, other = (left, right) if left_label.graded_relevance > right_label.graded_relevance else (right, left)
                pair_total += 1; pair_correct += int(positions[preferred] < positions[other])
                if abs(left_label.graded_relevance - right_label.graded_relevance) == 1: hard_total += 1; hard_correct += int(positions[preferred] < positions[other])
            effective_left = left_label.graded_relevance if left_label.hard_eligibility == "pass" else 0
            effective_right = right_label.graded_relevance if right_label.hard_eligibility == "pass" else 0
            if effective_left != effective_right:
                preferred, other = (left, right) if effective_left > effective_right else (right, left)
                eligible_pair_total += 1; eligible_pair_correct += int(positions[preferred] < positions[other])
        for candidate_id, label in labels.items():
            assessment = assessments[candidate_id]; candidates += 1; uncertainties.append(assessment.uncertainty)
            hard_violation += int(label.hard_eligibility == "fail" and assessment.shortlist_eligible)
            unsupported += int(label.evidence_sufficiency == "insufficient" and assessment.shortlist_eligible)
            eligible_exclusion += int(label.hard_eligibility == "pass" and not assessment.shortlist_eligible and not assessment.human_review_required)
            qualified_exclusion += int(label.hard_eligibility == "pass" and label.graded_relevance >= 2 and not assessment.shortlist_eligible and not assessment.human_review_required)
            unknown_auto += int(label.hard_eligibility == "unknown" and not assessment.human_review_required)
            high_risk_auto += int(label.fraud_or_inconsistency_risk == "high" and assessment.shortlist_eligible and not assessment.human_review_required)
            required, routed = label.human_review_required, assessment.human_review_required
            review_tp += int(required and routed); review_fp += int(not required and routed); review_fn += int(required and not routed); review_tn += int(not required and not routed)
            is_correct = assessment.eligibility == label.hard_eligibility and not (label.hard_eligibility == "fail" and assessment.shortlist_eligible)
            (correct_uncertainties if is_correct else incorrect_uncertainties).append(assessment.uncertainty)
    precision = review_tp / (review_tp + review_fp) if review_tp + review_fp else None; recall = review_tp / (review_tp + review_fn) if review_tp + review_fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return TalentEvaluationReport(len(records), candidates, no_qualified, applicable, rel_ndcg / len(records), policy_ndcg / len(records), qualified_found / qualified_total if qualified_total else 0.0, macro_recall_sum / applicable if applicable else None, pair_correct / pair_total if pair_total else 0.0, eligible_pair_correct / eligible_pair_total if eligible_pair_total else 0.0, hard_correct / hard_total if hard_total else 0.0, top1 / len(records), top5 / len(records), hard_violation / candidates, unsupported / candidates, qualified_exclusion / candidates, eligible_exclusion / candidates, unknown_auto / candidates, high_risk_auto / candidates, precision, recall, f1, review_fp / (review_fp + review_tn) if review_fp + review_tn else None, review_fn / (review_fn + review_tp) if review_fn + review_tp else None, (review_tp + review_fp) / candidates, mean(uncertainties), mean(correct_uncertainties) if correct_uncertainties else None, mean(incorrect_uncertainties) if incorrect_uncertainties else None, _agreement(records))


def bootstrap_confidence_intervals(records: list[TalentEvaluationRecord], submissions: list[TalentEvaluationSubmission], samples: int = 1_000, seed: int = 0) -> dict[str, ConfidenceInterval]:
    """Case-resampled 95% intervals; candidate rows are never independently sampled."""
    if samples < 2: raise ValueError("at least two bootstrap samples are required")
    by_case = {item.case_id: item for item in submissions}; generator = random.Random(seed)
    values: dict[str, list[float]] = {"relevance_ndcg_at_5": [], "policy_adjusted_ndcg_at_5": [], "qualified_recall_at_5_micro": []}
    for _ in range(samples):
        draw = [generator.choice(records) for _ in records]
        # Cases are copied with unique synthetic identifiers so evaluate can retain strict duplicate checks.
        copied = [record.model_copy(update={"case_id": f"bootstrap-{index}"}) for index, record in enumerate(draw)]
        copied_submissions = [by_case[record.case_id].model_copy(update={"case_id": f"bootstrap-{index}"}) for index, record in enumerate(draw)]
        report = evaluate(copied, copied_submissions)
        for name in values: values[name].append(getattr(report, name))
    return {name: ConfidenceInterval(sorted(points)[int(0.025 * (samples - 1))], sorted(points)[int(0.975 * (samples - 1))]) for name, points in values.items()}


def evaluate_by_slice(records: list[TalentEvaluationRecord], submissions: list[TalentEvaluationSubmission], slice_name: str, minimum_cases: int = 30) -> dict[str, TalentEvaluationReport]:
    allowed = {"job_family", "seniority", "region", "language", "profile_completeness"}
    if slice_name not in allowed: raise ValueError(f"unsupported slice {slice_name!r}; choose one of {sorted(allowed)}")
    by_case = {item.case_id: item for item in submissions}; groups: dict[str, list[TalentEvaluationRecord]] = {}
    for record in records:
        if slice_name == "profile_completeness":
            value = "sparse" if mean(item.profile_completeness for item in record.candidates) < .5 else "mixed" if mean(item.profile_completeness for item in record.candidates) < .8 else "rich"
        else: value = getattr(record.job, slice_name) or "unspecified"
        groups.setdefault(value, []).append(record)
    if minimum_cases < 1: raise ValueError("minimum_cases must be positive")
    return {
        value: replace(evaluate(group, [by_case[item.case_id] for item in group]), minimum_sample_warning=len(group) < minimum_cases)
        for value, group in sorted(groups.items())
    }


def load_jsonl(path: Path) -> list[TalentEvaluationRecord]:
    return [TalentEvaluationRecord.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate Talent Integrity pilot submissions")
    parser.add_argument("records", type=Path); parser.add_argument("submissions", type=Path)
    args = parser.parse_args()
    submissions = [TalentEvaluationSubmission.model_validate(json.loads(line)) for line in args.submissions.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(json.dumps(asdict(evaluate(load_jsonl(args.records), submissions)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
