from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from stage4_razor_reranker import RazorReranker, RerankContext, ValenceStageError

MAX_DATASET_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RankingEvaluation:
    batches: int
    failed_batches: int
    top1_accuracy: float
    top1_ci95_low: float
    top1_ci95_high: float
    top5_winner_recall: float
    mean_reciprocal_rank: float
    ndcg_at_5: float


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return max(0.0, center - spread), min(1.0, center + spread)


def _dcg(grades: list[float]) -> float:
    return sum((2.0**grade - 1.0) / math.log2(index + 2.0) for index, grade in enumerate(grades))


def _context(value: Any) -> RerankContext:
    if not isinstance(value, dict):
        raise ValueError("context must be an object")
    authorized = value.get("authorized_channels")
    if not isinstance(authorized, list) or not authorized:
        raise ValueError("authorized_channels must be a non-empty array")
    return RerankContext(
        target_channel=str(value["target_channel"]),
        authorized_channels=frozenset(str(item) for item in authorized),
        target_colorway=str(value["target_colorway"]),
        target_era_year=int(value["target_era_year"]),
    )


def evaluate_records(records: list[dict[str, Any]]) -> RankingEvaluation:
    if not records:
        raise ValueError("evaluation dataset is empty")
    top1 = 0
    top5 = 0
    reciprocal_rank = 0.0
    ndcg = 0.0
    failures = 0
    evaluated = 0

    for record in records:
        profiles = record.get("profiles")
        relevance = record.get("relevance")
        if not isinstance(profiles, list) or not isinstance(relevance, dict):
            raise ValueError("each record requires profiles and relevance")
        grades = {str(key): float(value) for key, value in relevance.items()}
        if not grades or any(not math.isfinite(value) or value < 0.0 for value in grades.values()):
            raise ValueError("relevance grades must be finite non-negative numbers")
        best_grade = max(grades.values())
        if best_grade <= 0.0:
            raise ValueError("each record requires at least one relevant candidate")
        profile_ids = {str(profile.get("id")) for profile in profiles if isinstance(profile, dict)}
        if not set(grades).issubset(profile_ids):
            raise ValueError("relevance contains a candidate absent from profiles")

        evaluated += 1
        try:
            result = RazorReranker().rerank(profiles, _context(record.get("context")))
        except ValenceStageError:
            failures += 1
            continue
        ranked = [candidate.id for candidate in result.selected]
        winners = {candidate_id for candidate_id, grade in grades.items() if grade == best_grade}
        top1 += int(ranked[0] in winners)
        winner_rank = next((index for index, candidate_id in enumerate(ranked, 1) if candidate_id in winners), None)
        if winner_rank is not None:
            top5 += 1
            reciprocal_rank += 1.0 / winner_rank
        predicted_grades = [grades.get(candidate_id, 0.0) for candidate_id in ranked[:5]]
        ideal_grades = sorted(grades.values(), reverse=True)[:5]
        ideal = _dcg(ideal_grades)
        ndcg += _dcg(predicted_grades) / ideal

    low, high = _wilson(top1, evaluated)
    return RankingEvaluation(
        batches=evaluated,
        failed_batches=failures,
        top1_accuracy=top1 / evaluated,
        top1_ci95_low=low,
        top1_ci95_high=high,
        top5_winner_recall=top5 / evaluated,
        mean_reciprocal_rank=reciprocal_rank / evaluated,
        ndcg_at_5=ndcg / evaluated,
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_DATASET_BYTES:
        raise ValueError("evaluation dataset exceeds 512 MiB")
    records: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if len(raw_line) > MAX_LINE_BYTES:
                raise ValueError(f"line {line_number} exceeds 5 MiB")
            if not raw_line.strip():
                continue
            value = json.loads(raw_line)
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number} must contain an object")
            records.append(value)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Stage 4 against independently labeled JSONL")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-top1", type=float, default=None)
    parser.add_argument("--min-ndcg", type=float, default=None)
    args = parser.parse_args()
    report = evaluate_records(load_jsonl(args.dataset))
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    if args.min_top1 is not None and report.top1_ci95_low < args.min_top1:
        return 2
    if args.min_ndcg is not None and report.ndcg_at_5 < args.min_ndcg:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
