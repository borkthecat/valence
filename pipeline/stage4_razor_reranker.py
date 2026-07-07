#!/usr/bin/env python3
"""
Valence Gateway :: Stage 4 :: Razor Reranking Engine
====================================================

Pure-stdlib, deterministic reranking engine for the Valence candidate
identification pipeline. It ingests a batch of up to 50 hydrated candidate
profiles from Stage 3, applies a fixed compliance and integrity scoring
matrix, removes integrity violators outright, and slices the survivors down
to exactly the top OUTPUT_POOL_SIZE profiles for Stage 5 cognitive
verification.

Design guarantees:
  - Deterministic: identical input plus identical context yields identical
    output, including tie ordering (ties break on candidate id).
  - Fail-closed: a batch that cannot yield a full high-integrity pool raises
    rather than padding the result with disqualified candidates. Bad or
    unauthorized actors can never leak past the filter into Stage 5.
  - No third-party dependencies. Python 3.11+.

Scoring matrix (base score 100.0 per candidate):
  - Age structurally anomalous (< 0 or > 120): -40.0 and DISQUALIFIED.
  - Age > 80 (but <= 120): -10.0.
  - Anniversary marker True: +15.0.
  - Channel in the authorized allowlist: +20.0.
  - Channel not authorized: -50.0 and DISQUALIFIED (never leaks past).
  - Colorway exact match to target: +10.0.
  - Historical era deviation > 100 years: -45.0; else > 50 years: -15.0.

Disqualification is a hard gate applied before ranking. The penalty is still
recorded on the score for telemetry and audit transparency, but a
disqualified candidate is removed from the eligible pool regardless of score.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

from config import get_settings


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_SCORE: Final[float] = 100.0
MAX_BATCH_SIZE: Final[int] = 50
OUTPUT_POOL_SIZE: Final[int] = 5

AGE_ANOMALY_PENALTY: Final[float] = -40.0
AGE_ELEVATED_PENALTY: Final[float] = -10.0
ANNIVERSARY_BOOST: Final[float] = 15.0
CHANNEL_AUTHORIZED_BOOST: Final[float] = 20.0
CHANNEL_UNAUTHORIZED_PENALTY: Final[float] = -50.0
COLORWAY_MATCH_BOOST: Final[float] = 10.0
ERA_FAR_PENALTY: Final[float] = -45.0
ERA_NEAR_PENALTY: Final[float] = -15.0

AGE_ANOMALY_LOW: Final[float] = 0.0
AGE_ANOMALY_HIGH: Final[float] = 120.0
AGE_ELEVATED_THRESHOLD: Final[float] = 80.0
ERA_FAR_THRESHOLD: Final[float] = 100.0
ERA_NEAR_THRESHOLD: Final[float] = 50.0

# Required key -> accepted python type(s) for incoming candidate dicts.
_REQUIRED_SCHEMA: Final[dict[str, tuple[type, ...]]] = {
    "id": (str,),
    "age": (int, float),
    "anniversary": (bool,),
    "channel": (str,),
    "colorway": (str,),
    "era_year": (int, float),
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ValenceStageError(Exception):
    """Base class for every Stage 4 failure."""


class CandidateValidationError(ValenceStageError):
    """Raised when an incoming candidate dict has a bad shape, key, or type."""


class BatchSizeError(ValenceStageError):
    """Raised when a batch is empty or exceeds MAX_BATCH_SIZE."""


class InsufficientEligibleCandidatesError(ValenceStageError):
    """
    Raised when fewer than OUTPUT_POOL_SIZE candidates survive the integrity
    gate. Padding with disqualified candidates would leak bad actors, so the
    engine fails closed instead.
    """


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RerankContext:
    """Target profile and policy the batch is scored against."""

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
    """A validated, immutable Stage 3 candidate profile."""

    id: str
    age: float
    anniversary: bool
    channel: str
    colorway: str
    era_year: float


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Full, auditable trace of how a candidate score was produced."""

    candidate_id: str
    base: float
    adjustments: tuple[tuple[str, float], ...]
    final_score: float
    disqualified: bool
    disqualifiers: tuple[str, ...]
    anomaly_count: int


@dataclass(slots=True)
class EngineTelemetry:
    """Accumulating operational counters rendered by the dashboard."""

    batches_handled: int = 0
    items_processed: int = 0
    output_yield: int = 0
    compliance_anomalies: int = 0
    latency_ms: float = 0.0
    disqualified_total: int = 0


@dataclass(frozen=True, slots=True)
class RerankResult:
    """Outcome of a single batch rerank."""

    selected: tuple[Candidate, ...]
    breakdowns: tuple[ScoreBreakdown, ...]
    eligible_count: int
    disqualified_count: int
    anomaly_count: int
    latency_ms: float


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_candidate(raw: Any) -> Candidate:
    """
    Coerce and validate a single raw candidate dict into a Candidate.

    Raises CandidateValidationError on any shape, key, or type violation.
    Note: bool is a subclass of int in Python, so numeric fields explicitly
    reject bool to keep the schema honest.
    """
    if not isinstance(raw, dict):
        raise CandidateValidationError(
            f"candidate must be a dict, received {type(raw).__name__}"
        )

    missing = [key for key in _REQUIRED_SCHEMA if key not in raw]
    if missing:
        raise CandidateValidationError(f"candidate missing keys: {sorted(missing)}")

    extra = [key for key in raw if key not in _REQUIRED_SCHEMA]
    if extra:
        raise CandidateValidationError(f"candidate has unknown keys: {sorted(extra)}")

    for key, accepted in _REQUIRED_SCHEMA.items():
        value = raw[key]
        # Reject bool where a number is expected (bool is an int subclass).
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

    return Candidate(
        id=candidate_id,
        age=float(raw["age"]),
        anniversary=bool(raw["anniversary"]),
        channel=raw["channel"].strip(),
        colorway=raw["colorway"].strip(),
        era_year=float(raw["era_year"]),
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RazorReranker:
    """
    Stateful reranking engine. State is limited to accumulating telemetry
    across batches; scoring itself is a pure function of (candidate, context).
    """

    def __init__(self) -> None:
        self._telemetry = EngineTelemetry()

    @property
    def telemetry(self) -> EngineTelemetry:
        return self._telemetry

    def score_candidate(
        self, candidate: Candidate, context: RerankContext
    ) -> ScoreBreakdown:
        """Apply the full deterministic matrix to one candidate."""
        adjustments: list[tuple[str, float]] = []
        disqualifiers: list[str] = []
        anomalies = 0

        if candidate.age < AGE_ANOMALY_LOW or candidate.age > AGE_ANOMALY_HIGH:
            adjustments.append(("age_structurally_anomalous", AGE_ANOMALY_PENALTY))
            disqualifiers.append("age_structurally_anomalous")
            anomalies += 1
        elif candidate.age > AGE_ELEVATED_THRESHOLD:
            adjustments.append(("age_elevated", AGE_ELEVATED_PENALTY))

        if candidate.anniversary:
            adjustments.append(("anniversary_marker", ANNIVERSARY_BOOST))

        if candidate.channel in context.authorized_channels:
            adjustments.append(("channel_authorized", CHANNEL_AUTHORIZED_BOOST))
        else:
            adjustments.append(("channel_unauthorized", CHANNEL_UNAUTHORIZED_PENALTY))
            disqualifiers.append("channel_unauthorized")
            anomalies += 1

        if candidate.colorway.casefold() == context.target_colorway.casefold():
            adjustments.append(("colorway_match", COLORWAY_MATCH_BOOST))

        deviation = abs(candidate.era_year - context.target_era_year)
        if deviation > ERA_FAR_THRESHOLD:
            adjustments.append(("era_deviation_far", ERA_FAR_PENALTY))
        elif deviation > ERA_NEAR_THRESHOLD:
            adjustments.append(("era_deviation_near", ERA_NEAR_PENALTY))

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
        """
        Validate, score, gate, and slice a batch down to exactly
        OUTPUT_POOL_SIZE high-integrity candidates.
        """
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

        # Deterministic ranking: highest score first, ties broken by id.
        eligible.sort(key=lambda b: (-b.final_score, b.candidate_id))
        top = eligible[:OUTPUT_POOL_SIZE]
        selected = tuple(by_id[b.candidate_id] for b in top)

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
        )


# ---------------------------------------------------------------------------
# Operational dashboard
# ---------------------------------------------------------------------------

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
    """Return a beautifully aligned, scannable terminal telemetry panel."""
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
    """Return an aligned table of the final selected pool with scores."""
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


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

def _default_context() -> RerankContext:
    settings = get_settings()
    return RerankContext(
        target_channel=settings.target_channel,
        authorized_channels=settings.authorized_channels,
        target_colorway=settings.target_colorway,
        target_era_year=settings.target_era,
    )


def _fixed_test_context() -> RerankContext:
    """Environment-independent context so unit assertions stay deterministic."""
    return RerankContext(
        target_channel="boutique-authorized",
        authorized_channels=frozenset(
            {"boutique-authorized", "brand-direct", "certified-partner"}
        ),
        target_colorway="midnight-sapphire",
        target_era_year=1998,
    )


def _sample_batch() -> list[dict[str, Any]]:
    """A representative Stage 3 batch mixing strong, weak, and bad actors."""
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
        # Bad actor: unauthorized channel. Must never leak past.
        {"id": "cand-graymarket", "age": 26, "anniversary": True,
         "channel": "unauthorized-reseller", "colorway": "midnight-sapphire",
         "era_year": 1998},
        # Bad actor: structurally anomalous age.
        {"id": "cand-corrupt", "age": 305, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "midnight-sapphire",
         "era_year": 1998},
    ]


# ---------------------------------------------------------------------------
# Verification suite (inline assertions)
# ---------------------------------------------------------------------------

def _run_verification() -> None:
    """
    Self-check the implementation against every rule of the specification.
    Any failure raises AssertionError and aborts before the demo dashboard.
    """
    context = _fixed_test_context()
    engine = RazorReranker()

    # 1. Exact scoring math.
    perfect = validate_candidate(
        {"id": "perfect", "age": 30, "anniversary": True,
         "channel": "boutique-authorized", "colorway": "midnight-sapphire",
         "era_year": 1998}
    )
    b = engine.score_candidate(perfect, context)
    assert b.final_score == 145.0, b.final_score  # 100 +15 +20 +10
    assert not b.disqualified

    elevated = validate_candidate(
        {"id": "elevated", "age": 90, "anniversary": False,
         "channel": "brand-direct", "colorway": "no-match",
         "era_year": 1938}  # deviation 60 -> near penalty
    )
    b = engine.score_candidate(elevated, context)
    assert b.final_score == 95.0, b.final_score  # 100 -10 +20 -15

    far_era = validate_candidate(
        {"id": "far", "age": 30, "anniversary": False,
         "channel": "brand-direct", "colorway": "no-match",
         "era_year": 1800}  # deviation 198 -> far penalty
    )
    b = engine.score_candidate(far_era, context)
    assert b.final_score == 75.0, b.final_score  # 100 +20 -45

    # 2. Disqualification gates.
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
    assert unauthorized.final_score == 50.0, unauthorized.final_score  # 100 -50

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

    # 3. Validation rejects malformed payloads.
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

    # 4. End-to-end: exactly 5 out, no bad actors, deterministic.
    result = engine.rerank(_sample_batch(), context)
    assert len(result.selected) == OUTPUT_POOL_SIZE, len(result.selected)
    selected_ids = {c.id for c in result.selected}
    assert "cand-graymarket" not in selected_ids, "unauthorized actor leaked"
    assert "cand-corrupt" not in selected_ids, "anomalous actor leaked"
    assert result.disqualified_count == 2, result.disqualified_count
    assert result.anomaly_count == 2, result.anomaly_count

    # Determinism: same input, same order.
    again = RazorReranker().rerank(_sample_batch(), context)
    assert [c.id for c in again.selected] == [c.id for c in result.selected]

    # 5. Batch bounds.
    for bad_batch, exc in [
        ([], BatchSizeError),
        (_sample_batch() * 7, BatchSizeError),  # 56 > 50
    ]:
        try:
            engine.rerank(bad_batch, context)
        except exc:
            pass
        else:
            raise AssertionError("batch bounds not enforced")

    # 6. Fail-closed when too few survive the integrity gate.
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _run_verification()

    context = _default_context()
    engine = RazorReranker()

    # Process a few batches so the dashboard shows meaningful aggregates.
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
