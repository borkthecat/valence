from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from ranking_evaluator import _context, _dcg, load_jsonl
from stage4_razor_reranker import RazorReranker, validate_candidate


GROUPS = {
    "channel": frozenset({"channel_target_match", "channel_authorized", "channel_unauthorized"}),
    "era": frozenset({"era_deviation_far", "era_deviation_near", "era_proximity"}),
    "evidence": frozenset({"evidence_insufficient", "evidence_weak", "evidence_strong"}),
    "relevance": frozenset({"source_relevance"}),
    "other": frozenset({"age_structurally_anomalous", "age_elevated", "anniversary_marker", "colorway_match"}),
}


def _record_key(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record.get("relevance"), sort_keys=True).encode("utf-8")).hexdigest()


def _score(records: list[dict[str, Any]], weights: dict[str, float]) -> dict[str, float]:
    top1 = ndcg = 0.0
    for record in records:
        context = _context(record["context"])
        grades = {str(key): float(value) for key, value in record["relevance"].items()}
        ranked = []
        for raw in record["profiles"]:
            candidate = validate_candidate(raw)
            breakdown = RazorReranker().score_candidate(candidate, context)
            if breakdown.disqualified:
                continue
            adjusted = 0.0
            for label, delta in breakdown.adjustments:
                group = next((name for name, labels in GROUPS.items() if label in labels), "other")
                adjusted += delta * weights[group]
            ranked.append((breakdown.base + adjusted, candidate.id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        ids = [candidate_id for _, candidate_id in ranked[:5]]
        best = max(grades.values())
        top1 += float(bool(ids) and grades.get(ids[0], 0.0) == best)
        ideal = _dcg(sorted(grades.values(), reverse=True)[:5])
        ndcg += _dcg([grades.get(candidate_id, 0.0) for candidate_id in ids]) / ideal if ideal else 0.0
    return {"records": len(records), "top1Accuracy": top1 / len(records), "ndcgAt5": ndcg / len(records)}


def sweep(records: list[dict[str, Any]], values: tuple[float, ...]) -> dict[str, Any]:
    ordered = sorted(records, key=_record_key)
    split = max(1, math.floor(len(ordered) * 0.7))
    calibration, held_out = ordered[:split], ordered[split:]
    if not held_out:
        raise ValueError("at least two ranking records are required")
    best_weights = None
    best_metrics = None
    for combination in itertools.product(values, repeat=len(GROUPS)):
        weights = dict(zip(GROUPS, combination, strict=True))
        metrics = _score(calibration, weights)
        if best_metrics is None or (metrics["ndcgAt5"], metrics["top1Accuracy"], tuple(-value for value in combination)) > (
            best_metrics["ndcgAt5"], best_metrics["top1Accuracy"], tuple(-best_weights[name] for name in GROUPS)
        ):
            best_weights, best_metrics = weights, metrics
    assert best_weights is not None and best_metrics is not None
    return {
        "partition": "deterministic-70-30-record-hash",
        "calibrationMetrics": best_metrics,
        "heldOutMetrics": _score(held_out, best_weights),
        "weights": best_weights,
        "gridValues": values,
        "combinations": len(values) ** len(GROUPS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep Stage 4 adjustment-group weights on a calibration split")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--values", default="0,0.5,1,1.5,2")
    parser.add_argument("--evidence-level", choices=("public_benchmark", "silver_pseudo_label"), default="public_benchmark")
    args = parser.parse_args()
    values = tuple(float(value) for value in args.values.split(","))
    report = sweep(load_jsonl(args.input), values)
    report["evidenceLevel"] = args.evidence_level
    report["candidateJobReleaseGateEligible"] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"weights": report["weights"], "heldOutMetrics": report["heldOutMetrics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
