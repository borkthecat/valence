#!/usr/bin/env python3

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Final

from config import get_settings






BASE_SCORE: Final[float] = 100.0
MAX_BATCH_SIZE: Final[int] = 50
OUTPUT_POOL_SIZE: Final[int] = 5

AGE_ANOMALY_PENALTY: Final[float] = -40.0
AGE_ELEVATED_MAX_PENALTY: Final[float] = -25.0
AGE_ELEVATED_PENALTY_PER_YEAR: Final[float] = -0.75
ANNIVERSARY_BOOST: Final[float] = 18.0
CHANNEL_TARGET_BOOST: Final[float] = 30.0
CHANNEL_AUTHORIZED_BOOST: Final[float] = 10.0
CHANNEL_UNAUTHORIZED_PENALTY: Final[float] = -50.0
COLORWAY_MATCH_BOOST: Final[float] = 16.0
ERA_FAR_PENALTY: Final[float] = -55.0
ERA_PENALTY_PER_YEAR: Final[float] = 0.50
EVIDENCE_MIN_QUALITY: Final[float] = 0.25
EVIDENCE_LOW_QUALITY_THRESHOLD: Final[float] = 0.60
EVIDENCE_HIGH_QUALITY_THRESHOLD: Final[float] = 0.90
EVIDENCE_LOW_MAX_PENALTY: Final[float] = -18.0
EVIDENCE_HIGH_BOOST: Final[float] = 6.0

AGE_ANOMALY_LOW: Final[float] = 0.0
AGE_ANOMALY_HIGH: Final[float] = 120.0
AGE_ELEVATED_THRESHOLD: Final[float] = 80.0
ERA_FAR_THRESHOLD: Final[float] = 100.0
ERA_NEAR_THRESHOLD: Final[float] = 50.0


_REQUIRED_SCHEMA: Final[dict[str, tuple[type, ...]]] = {
    "id": (str,),
    "age": (int, float),
    "anniversary": (bool,),
    "channel": (str,),
    "colorway": (str,),
    "era_year": (int, float),
}
_OPTIONAL_SCHEMA: Final[dict[str, tuple[type, ...]]] = {
    "entity_type": (str,),
    "title": (str,),
    "description": (str,),
    "attributes": (dict,),
    "signals": (dict,),
    "images": (list,),
    "evidence_quality_score": (int, float),
}






class ValenceStageError(Exception):
    pass

class CandidateValidationError(ValenceStageError):
    pass

class BatchSizeError(ValenceStageError):
    pass

class InsufficientEligibleCandidatesError(ValenceStageError):
    pass





@dataclass(frozen=True, slots=True)
class RerankContext:

    target_channel: str
    authorized_channels: frozenset[str]
    target_colorway: str
    target_era_year: int

    def __post_init__(self) -> None:
        if self.target_channel not in self.authorized_channels:
            raise ValenceStageError(
                "target_channel must itself be present in authorized_channels"
            )


@dataclass(frozen=True, slots=True)
class Candidate:

    id: str
    age: float
    anniversary: bool
    channel: str
    colorway: str
    era_year: float
    entity_type: str | None = None
    title: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None
    signals: dict[str, Any] | None = None
    images: tuple[dict[str, Any], ...] = ()
    evidence_quality_score: float | None = None


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:

    candidate_id: str
    base: float
    adjustments: tuple[tuple[str, float], ...]
    final_score: float
    disqualified: bool
    disqualifiers: tuple[str, ...]
    anomaly_count: int


@dataclass(slots=True)
class EngineTelemetry:

    batches_handled: int = 0
    items_processed: int = 0
    output_yield: int = 0
    compliance_anomalies: int = 0
    latency_ms: float = 0.0
    disqualified_total: int = 0


@dataclass(frozen=True, slots=True)
class RerankResult:

    selected: tuple[Candidate, ...]
    breakdowns: tuple[ScoreBreakdown, ...]
    eligible_count: int
    disqualified_count: int
    anomaly_count: int
    latency_ms: float
    score_margin: float


@dataclass(frozen=True, slots=True)
class QualityReport:
    evaluated_batches: int
    top1_matches: int
    top5_contains_oracle: int
    fail_closed_batches: int

    @property
    def top1_accuracy(self) -> float:
        return self.top1_matches / self.evaluated_batches if self.evaluated_batches else 0.0

    @property
    def top5_recall(self) -> float:
        return (
            self.top5_contains_oracle / self.evaluated_batches
            if self.evaluated_batches
            else 0.0
        )






def validate_candidate(raw: Any) -> Candidate:
    if not isinstance(raw, dict):
        raise CandidateValidationError(
            f"candidate must be a dict, received {type(raw).__name__}"
        )

    missing = [key for key in _REQUIRED_SCHEMA if key not in raw]
    if missing:
        raise CandidateValidationError(f"candidate missing keys: {sorted(missing)}")

    extra = [key for key in raw if key not in _REQUIRED_SCHEMA and key not in _OPTIONAL_SCHEMA]
    if extra:
        raise CandidateValidationError(f"candidate has unknown keys: {sorted(extra)}")

    schema = {**_REQUIRED_SCHEMA, **{key: value for key, value in _OPTIONAL_SCHEMA.items() if key in raw}}
    for key, accepted in schema.items():
        value = raw[key]

        if accepted in ((int, float),) and isinstance(value, bool):
            raise CandidateValidationError(
                f"key '{key}' must be numeric, received bool"
            )
        if not isinstance(value, accepted):
            names = " or ".join(t.__name__ for t in accepted)
            raise CandidateValidationError(
                f"key '{key}' must be {names}, received {type(value).__name__}"
            )

    candidate_id = raw["id"].strip()
    if not candidate_id:
        raise CandidateValidationError("key 'id' must be a non-empty string")

    evidence_quality_score = None
    if "evidence_quality_score" in raw:
        evidence_quality_score = float(raw["evidence_quality_score"])
        if evidence_quality_score < 0.0 or evidence_quality_score > 1.0:
            raise CandidateValidationError("key 'evidence_quality_score' must be between 0 and 1")

    return Candidate(
        id=candidate_id,
        age=float(raw["age"]),
        anniversary=bool(raw["anniversary"]),
        channel=raw["channel"].strip(),
        colorway=raw["colorway"].strip(),
        era_year=float(raw["era_year"]),
        entity_type=raw.get("entity_type", None),
        title=raw.get("title", None),
        description=raw.get("description", None),
        attributes=raw.get("attributes", None),
        signals=raw.get("signals", None),
        images=tuple(raw.get("images", ())),
        evidence_quality_score=evidence_quality_score,
    )






class RazorReranker:

    def __init__(self) -> None:
        self._telemetry = EngineTelemetry()

    @property
    def telemetry(self) -> EngineTelemetry:
        return self._telemetry

    def score_candidate(
        self, candidate: Candidate, context: RerankContext
    ) -> ScoreBreakdown:
        adjustments: list[tuple[str, float]] = []
        disqualifiers: list[str] = []
        anomalies = 0

        if candidate.age < AGE_ANOMALY_LOW or candidate.age > AGE_ANOMALY_HIGH:
            adjustments.append(("age_structurally_anomalous", AGE_ANOMALY_PENALTY))
            disqualifiers.append("age_structurally_anomalous")
            anomalies += 1
        elif candidate.age > AGE_ELEVATED_THRESHOLD:
            penalty = max(
                AGE_ELEVATED_MAX_PENALTY,
                (candidate.age - AGE_ELEVATED_THRESHOLD) * AGE_ELEVATED_PENALTY_PER_YEAR,
            )
            adjustments.append(("age_elevated", round(penalty, 3)))

        if candidate.anniversary:
            adjustments.append(("anniversary_marker", ANNIVERSARY_BOOST))

        if candidate.channel == context.target_channel:
            adjustments.append(("channel_target_match", CHANNEL_TARGET_BOOST))
        elif candidate.channel in context.authorized_channels:
            adjustments.append(("channel_authorized", CHANNEL_AUTHORIZED_BOOST))
        else:
            adjustments.append(("channel_unauthorized", CHANNEL_UNAUTHORIZED_PENALTY))
            disqualifiers.append("channel_unauthorized")
            anomalies += 1

        if candidate.colorway.casefold() == context.target_colorway.casefold():
            adjustments.append(("colorway_match", COLORWAY_MATCH_BOOST))

        deviation = abs(candidate.era_year - context.target_era_year)
        if deviation > 0:
            penalty = max(ERA_FAR_PENALTY, -(deviation * ERA_PENALTY_PER_YEAR))
            label = (
                "era_deviation_far"
                if deviation > ERA_FAR_THRESHOLD
                else "era_deviation_near"
                if deviation > ERA_NEAR_THRESHOLD
                else "era_proximity"
            )
            adjustments.append((label, round(penalty, 3)))

        if candidate.evidence_quality_score is not None:
            quality = candidate.evidence_quality_score
            if quality < EVIDENCE_MIN_QUALITY:
                adjustments.append(("evidence_insufficient", EVIDENCE_LOW_MAX_PENALTY))
                disqualifiers.append("evidence_insufficient")
                anomalies += 1
            elif quality < EVIDENCE_LOW_QUALITY_THRESHOLD:
                ratio = (
                    (EVIDENCE_LOW_QUALITY_THRESHOLD - quality)
                    / EVIDENCE_LOW_QUALITY_THRESHOLD
                )
                adjustments.append(
                    ("evidence_weak", round(EVIDENCE_LOW_MAX_PENALTY * ratio, 3))
                )
            elif quality >= EVIDENCE_HIGH_QUALITY_THRESHOLD:
                adjustments.append(("evidence_strong", EVIDENCE_HIGH_BOOST))

        final_score = BASE_SCORE + sum(delta for _, delta in adjustments)

        return ScoreBreakdown(
            candidate_id=candidate.id,
            base=BASE_SCORE,
            adjustments=tuple(adjustments),
            final_score=final_score,
            disqualified=bool(disqualifiers),
            disqualifiers=tuple(disqualifiers),
            anomaly_count=anomalies,
        )

    def rerank(
        self, raw_batch: list[dict[str, Any]], context: RerankContext
    ) -> RerankResult:
        if not raw_batch:
            raise BatchSizeError("batch is empty; nothing to rerank")
        if len(raw_batch) > MAX_BATCH_SIZE:
            raise BatchSizeError(
                f"batch of {len(raw_batch)} exceeds MAX_BATCH_SIZE={MAX_BATCH_SIZE}"
            )

        started = time.perf_counter()

        candidates = [validate_candidate(raw) for raw in raw_batch]

        seen_ids: set[str] = set()
        for candidate in candidates:
            if candidate.id in seen_ids:
                raise CandidateValidationError(f"duplicate candidate id: {candidate.id}")
            seen_ids.add(candidate.id)

        breakdowns = [self.score_candidate(c, context) for c in candidates]
        by_id = {c.id: c for c in candidates}

        anomaly_count = sum(b.anomaly_count for b in breakdowns)
        disqualified_count = sum(1 for b in breakdowns if b.disqualified)

        eligible = [b for b in breakdowns if not b.disqualified]
        if len(eligible) < OUTPUT_POOL_SIZE:
            raise InsufficientEligibleCandidatesError(
                f"only {len(eligible)} eligible candidate(s); "
                f"need {OUTPUT_POOL_SIZE} to form a high-integrity pool"
            )


        eligible.sort(key=lambda b: (-b.final_score, b.candidate_id))
        top = eligible[:OUTPUT_POOL_SIZE]
        selected = tuple(by_id[b.candidate_id] for b in top)
        score_margin = (
            top[0].final_score - top[1].final_score
            if len(top) > 1
            else top[0].final_score
        )

        latency_ms = (time.perf_counter() - started) * 1000.0

        self._telemetry.batches_handled += 1
        self._telemetry.items_processed += len(candidates)
        self._telemetry.output_yield += len(selected)
        self._telemetry.compliance_anomalies += anomaly_count
        self._telemetry.disqualified_total += disqualified_count
        self._telemetry.latency_ms += latency_ms

        return RerankResult(
            selected=selected,
            breakdowns=tuple(breakdowns),
            eligible_count=len(eligible),
            disqualified_count=disqualified_count,
            anomaly_count=anomaly_count,
            latency_ms=latency_ms,
            score_margin=score_margin,
        )


def result_to_stage5_pool(result: RerankResult) -> list[dict[str, Any]]:
    score_by_id = {b.candidate_id: b.final_score for b in result.breakdowns}

    def to_record(candidate: Candidate) -> dict[str, Any]:
        record = {
            "id": candidate.id,
            "age": candidate.age,
            "anniversary": candidate.anniversary,
            "channel": candidate.channel,
            "colorway": candidate.colorway,
            "era_year": int(candidate.era_year),
            "score": round(score_by_id[candidate.id], 3),
        }
        if candidate.entity_type is not None:
            record["entity_type"] = candidate.entity_type
        if candidate.title is not None:
            record["title"] = candidate.title
        if candidate.description is not None:
            record["description"] = candidate.description
        if candidate.attributes is not None:
            record["attributes"] = candidate.attributes
        if candidate.signals is not None:
            record["signals"] = candidate.signals
        if candidate.images:
            record["images"] = list(candidate.images)
        if candidate.evidence_quality_score is not None:
            record["evidence_quality_score"] = round(candidate.evidence_quality_score, 3)
        return record

    return [to_record(candidate) for candidate in result.selected]






_DASH_INNER_WIDTH: Final[int] = 60


def _center_row(text: str) -> str:
    return "|" + text.center(_DASH_INNER_WIDTH) + "|"


def _metric_row(label: str, value: str) -> str:
    gutter = 2
    usable = _DASH_INNER_WIDTH - (gutter * 2)
    label_field = usable // 2
    value_field = usable - label_field
    body = (
        (" " * gutter)
        + label.ljust(label_field)
        + value.rjust(value_field)
        + (" " * gutter)
    )
    return "|" + body + "|"


def render_dashboard(telemetry: EngineTelemetry) -> str:
    top = "+" + ("-" * _DASH_INNER_WIDTH) + "+"
    sep = "+" + ("-" * _DASH_INNER_WIDTH) + "+"

    avg_latency = (
        telemetry.latency_ms / telemetry.batches_handled
        if telemetry.batches_handled
        else 0.0
    )

    lines = [
        top,
        _center_row("VALENCE GATEWAY  //  STAGE 4"),
        _center_row("Razor Reranking Engine  ::  Live Telemetry"),
        sep,
        _metric_row("Batches handled", f"{telemetry.batches_handled:,}"),
        _metric_row("Items processed", f"{telemetry.items_processed:,}"),
        _metric_row("Sliced output yield", f"{telemetry.output_yield:,}"),
        _metric_row("Compliance anomalies", f"{telemetry.compliance_anomalies:,}"),
        _metric_row("Disqualified actors", f"{telemetry.disqualified_total:,}"),
        _metric_row("Total engine latency", f"{telemetry.latency_ms:.3f} ms"),
        _metric_row("Mean latency / batch", f"{avg_latency:.3f} ms"),
        top,
    ]
    return "\n".join(lines)


def render_pool(result: RerankResult) -> str:
    score_by_id = {b.candidate_id: b.final_score for b in result.breakdowns}
    header = "  RANK  SCORE     CANDIDATE ID          CHANNEL"
    rows = [header, "  " + ("-" * 52)]
    for rank, candidate in enumerate(result.selected, start=1):
        score = score_by_id[candidate.id]
        rows.append(
            f"  {rank:>4}  {score:>7.1f}   "
            f"{candidate.id[:20]:<20}  {candidate.channel}"
        )
    return "\n".join(rows)


def _synthetic_oracle_score(candidate: Candidate, context: RerankContext) -> float | None:
    if (
        candidate.age < AGE_ANOMALY_LOW
        or candidate.age > AGE_ANOMALY_HIGH
        or candidate.channel not in context.authorized_channels
    ):
        return None

    score = BASE_SCORE
    score += CHANNEL_TARGET_BOOST if candidate.channel == context.target_channel else CHANNEL_AUTHORIZED_BOOST
    score += ANNIVERSARY_BOOST if candidate.anniversary else 0.0
    score += COLORWAY_MATCH_BOOST if candidate.colorway.casefold() == context.target_colorway.casefold() else 0.0
    score -= min(abs(candidate.era_year - context.target_era_year) * ERA_PENALTY_PER_YEAR, abs(ERA_FAR_PENALTY))
    if candidate.age > AGE_ELEVATED_THRESHOLD:
        score += max(
            AGE_ELEVATED_MAX_PENALTY,
            (candidate.age - AGE_ELEVATED_THRESHOLD) * AGE_ELEVATED_PENALTY_PER_YEAR,
        )
    return score


def run_quality_validation(
    batches: int = 1_000,
    batch_size: int = MAX_BATCH_SIZE,
    seed: int = 20260708,
) -> QualityReport:
    from stage3_hydrator import FuzzDataGenerator

    context = _default_context()
    generator = FuzzDataGenerator(seed=seed)
    engine = RazorReranker()
    evaluated = 0
    top1_matches = 0
    top5_contains = 0
    fail_closed = 0

    for batch_index in range(batches):
        raw_batch = generator.generate(batch_size)
        for index, candidate in enumerate(raw_batch):
            candidate["id"] = f"quality-{batch_index:04d}-{index:02d}"

        candidates = [validate_candidate(raw) for raw in raw_batch]
        oracle_scores = [
            (_synthetic_oracle_score(candidate, context), candidate.id)
            for candidate in candidates
        ]
        eligible_oracle = [
            (score, candidate_id)
            for score, candidate_id in oracle_scores
            if score is not None
        ]
        if len(eligible_oracle) < OUTPUT_POOL_SIZE:
            fail_closed += 1
            continue

        evaluated += 1
        oracle_winner = sorted(eligible_oracle, key=lambda item: (-item[0], item[1]))[0][1]
        result = engine.rerank(raw_batch, context)
        selected_ids = [candidate.id for candidate in result.selected]
        if selected_ids[0] == oracle_winner:
            top1_matches += 1
        if oracle_winner in selected_ids:
            top5_contains += 1

    return QualityReport(
        evaluated_batches=evaluated,
        top1_matches=top1_matches,
        top5_contains_oracle=top5_contains,
        fail_closed_batches=fail_closed,
    )






def _default_context() -> RerankContext:
    settings = get_settings()
    return RerankContext(
        target_channel=settings.target_channel,
        authorized_channels=settings.authorized_channels,
        target_colorway=settings.target_colorway,
        target_era_year=settings.target_era,
    )


def _fixed_test_context() -> RerankContext:
    return RerankContext(
        target_channel="boutique-authorized",
        authorized_channels=frozenset(
            {"boutique-authorized", "brand-direct", "certified-partner"}
        ),
        target_colorway="midnight-sapphire",
        target_era_year=1998,
    )


def _sample_batch() -> list[dict[str, Any]]:
    return [
        {"id": "cand-alpha", "age": 26, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "midnight-sapphire",
         "era_year": 1998},
        {"id": "cand-bravo", "age": 26, "anniversary": True,
         "channel": "brand-direct", "colorway": "midnight-sapphire",
         "era_year": 2000},
        {"id": "cand-charlie", "age": 40, "anniversary": False,
         "channel": "certified-partner", "colorway": "midnight-sapphire",
         "era_year": 1995},
        {"id": "cand-delta", "age": 12, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "arctic-white",
         "era_year": 1988},
        {"id": "cand-echo", "age": 55, "anniversary": False,
         "channel": "brand-direct", "colorway": "arctic-white",
         "era_year": 1960},
        {"id": "cand-foxtrot", "age": 90, "anniversary": True,
         "channel": "certified-partner", "colorway": "midnight-sapphire",
         "era_year": 1998},

        {"id": "cand-graymarket", "age": 26, "anniversary": True,
         "channel": "unauthorized-reseller", "colorway": "midnight-sapphire",
         "era_year": 1998},

        {"id": "cand-corrupt", "age": 305, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "midnight-sapphire",
         "era_year": 1998},
    ]






def _run_verification() -> None:
    context = _fixed_test_context()
    engine = RazorReranker()


    perfect = validate_candidate(
        {"id": "perfect", "age": 30, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "midnight-sapphire",
         "era_year": 1998}
    )
    b = engine.score_candidate(perfect, context)
    assert b.final_score == 164.0, b.final_score
    assert not b.disqualified

    elevated = validate_candidate(
        {"id": "elevated", "age": 90, "anniversary": False,
         "channel": "brand-direct", "colorway": "no-match",
         "era_year": 1938}
    )
    b = engine.score_candidate(elevated, context)
    assert b.final_score == 72.5, b.final_score

    far_era = validate_candidate(
        {"id": "far", "age": 30, "anniversary": False,
         "channel": "brand-direct", "colorway": "no-match",
         "era_year": 1800}
    )
    b = engine.score_candidate(far_era, context)
    assert b.final_score == 55.0, b.final_score


    unauthorized = engine.score_candidate(
        validate_candidate(
            {"id": "bad", "age": 30, "anniversary": False,
             "channel": "unauthorized-reseller", "colorway": "no-match",
             "era_year": 1998}
        ),
        context,
    )
    assert unauthorized.disqualified
    assert "channel_unauthorized" in unauthorized.disqualifiers
    assert unauthorized.final_score == 50.0, unauthorized.final_score

    anomalous_age = engine.score_candidate(
        validate_candidate(
            {"id": "bad2", "age": -3, "anniversary": False,
             "channel": "brand-direct", "colorway": "no-match",
             "era_year": 1998}
        ),
        context,
    )
    assert anomalous_age.disqualified
    assert "age_structurally_anomalous" in anomalous_age.disqualifiers

    boundary = engine.score_candidate(
        validate_candidate(
            {"id": "boundary", "age": 120, "anniversary": True,
             "channel": "boutique-authorized", "colorway": " MIDNIGHT-SAPPHIRE ",
             "era_year": 1998}
        ),
        context,
    )
    assert not boundary.disqualified
    assert boundary.final_score == 139.0, boundary.final_score

    elevated_boundary = engine.score_candidate(
        validate_candidate(
            {"id": "elevated-boundary", "age": 81, "anniversary": True,
             "channel": "boutique-authorized", "colorway": "midnight-sapphire",
             "era_year": 1998}
        ),
        context,
    )
    assert elevated_boundary.final_score == 163.25, elevated_boundary.final_score

    far_boundary = engine.score_candidate(
        validate_candidate(
            {"id": "far-boundary", "age": 30, "anniversary": False,
             "channel": "brand-direct", "colorway": "no-match",
             "era_year": 2099}
        ),
        context,
    )
    assert far_boundary.final_score == 59.5, far_boundary.final_score


    for bad_payload, reason in [
        ("not-a-dict", "non-dict"),
        ({"id": "x"}, "missing keys"),
        ({"id": "x", "age": 20, "anniversary": True, "channel": "c",
          "colorway": "cw", "era_year": 1998, "extra": 1}, "unknown key"),
        ({"id": "x", "age": True, "anniversary": True, "channel": "c",
          "colorway": "cw", "era_year": 1998}, "bool as number"),
        ({"id": "", "age": 20, "anniversary": True, "channel": "c",
          "colorway": "cw", "era_year": 1998}, "empty id"),
    ]:
        try:
            validate_candidate(bad_payload)
        except CandidateValidationError:
            pass
        else:
            raise AssertionError(f"validation should have rejected: {reason}")


    result = engine.rerank(_sample_batch(), context)
    assert len(result.selected) == OUTPUT_POOL_SIZE, len(result.selected)
    selected_ids = {c.id for c in result.selected}
    assert "cand-graymarket" not in selected_ids, "unauthorized actor leaked"
    assert "cand-corrupt" not in selected_ids, "anomalous actor leaked"
    assert result.disqualified_count == 2, result.disqualified_count
    assert result.anomaly_count == 2, result.anomaly_count
    assert result.score_margin > 0.0, result.score_margin
    stage5_pool = result_to_stage5_pool(result)
    assert stage5_pool[0]["id"] == result.selected[0].id
    assert isinstance(stage5_pool[0]["score"], float)


    again = RazorReranker().rerank(_sample_batch(), context)
    assert [c.id for c in again.selected] == [c.id for c in result.selected]


    for bad_batch, exc in [
        ([], BatchSizeError),
        (_sample_batch() * 7, BatchSizeError),
    ]:
        try:
            engine.rerank(bad_batch, context)
        except exc:
            pass
        else:
            raise AssertionError("batch bounds not enforced")


    thin_batch = [
        {"id": f"bad-{i}", "age": 30, "anniversary": False,
         "channel": "unauthorized-reseller", "colorway": "x", "era_year": 1998}
        for i in range(6)
    ]
    try:
        engine.rerank(thin_batch, context)
    except InsufficientEligibleCandidatesError:
        pass
    else:
        raise AssertionError("engine should fail closed on thin eligible pool")

    quality = run_quality_validation(batches=1_000, batch_size=MAX_BATCH_SIZE)
    assert quality.top1_accuracy >= 0.995, quality
    assert quality.top5_recall >= 1.0, quality






def main() -> int:
    _run_verification()

    context = _default_context()
    engine = RazorReranker()


    last: RerankResult | None = None
    for _ in range(3):
        last = engine.rerank(_sample_batch(), context)

    print()
    print(render_dashboard(engine.telemetry))
    print()
    if last is not None:
        print("  Final high-integrity pool routed to Stage 5:")
        print()
        print(render_pool(last))
    print()
    print("  All inline verification assertions passed.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
