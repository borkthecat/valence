#!/usr/bin/env python3
"""Valence Pipeline Stage 3: Candidate Hydrator and Fuzz Generator.

Produces hydrated candidate profiles for the Stage 4 Razor Engine. The
FuzzDataGenerator emits large randomized batches with a controlled,
mathematically volatile distribution of edge cases so the deterministic
scoring and disqualification paths of Stage 4 can be validated at scale.

Runs clean under `python -W error`. Standard library only.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from config import get_settings

NEGATIVE_AGE_RATE: Final[float] = 0.05
UNAUTHORIZED_CHANNEL_RATE: Final[float] = 0.05
ERA_ANOMALY_RATE: Final[float] = 0.10

_COLORWAYS: Final[tuple[str, ...]] = (
    "midnight-sapphire",
    "arctic-white",
    "crimson-ember",
    "forest-moss",
    "graphite-slate",
)
_UNAUTHORIZED_CHANNELS: Final[tuple[str, ...]] = (
    "unauthorized-reseller",
    "grey-market",
    "unverified-third-party",
)


@dataclass(frozen=True, slots=True)
class FuzzProfile:
    """Metadata describing how a single generated profile was perturbed."""

    negative_age: bool
    unauthorized_channel: bool
    era_anomaly: bool


@dataclass(slots=True)
class GenerationReport:
    total: int
    negative_ages: int
    unauthorized_channels: int
    era_anomalies: int


class FuzzDataGenerator:
    """Generates randomized candidate profiles with a controlled fault mix."""

    def __init__(self, seed: int | None = 1337) -> None:
        self._rng = random.Random(seed)
        self._settings = get_settings()
        self._authorized = tuple(sorted(self._settings.authorized_channels))
        self._report = GenerationReport(0, 0, 0, 0)

    @property
    def report(self) -> GenerationReport:
        return self._report

    def generate(self, count: int) -> list[dict[str, Any]]:
        if count <= 0:
            raise ValueError("count must be positive")
        self._report = GenerationReport(count, 0, 0, 0)
        profiles: list[dict[str, Any]] = []
        for index in range(count):
            profiles.append(self._generate_one(index))
        return profiles

    def _generate_one(self, index: int) -> dict[str, Any]:
        rng = self._rng
        target_era = self._settings.target_era

        if rng.random() < NEGATIVE_AGE_RATE:
            age: float = float(rng.choice([-rng.randint(1, 40), rng.randint(121, 400)]))
            self._report.negative_ages += 1
        else:
            age = float(rng.randint(1, 75))

        if rng.random() < UNAUTHORIZED_CHANNEL_RATE:
            channel = rng.choice(_UNAUTHORIZED_CHANNELS)
            self._report.unauthorized_channels += 1
        else:
            channel = rng.choice(self._authorized)

        if rng.random() < ERA_ANOMALY_RATE:
            offset = rng.randint(101, 400) * rng.choice((-1, 1))
            era_year = target_era + offset
            self._report.era_anomalies += 1
        else:
            era_year = target_era + rng.randint(-30, 30)

        return {
            "id": f"fuzz-{index:06d}",
            "age": age,
            "anniversary": bool(rng.getrandbits(1)),
            "channel": channel,
            "colorway": rng.choice(_COLORWAYS),
            "era_year": era_year,
        }


def batched(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    """Yield successive fixed-size chunks, honoring the Stage 4 batch cap."""
    if size <= 0:
        raise ValueError("size must be positive")
    for start in range(0, len(items), size):
        yield items[start : start + size]


_DASH_WIDTH: Final[int] = 60


def render_dashboard(report: GenerationReport) -> str:
    def metric(label: str, value: str) -> str:
        gutter = 2
        usable = _DASH_WIDTH - gutter * 2
        left = usable // 2
        right = usable - left
        return "|" + (" " * gutter) + label.ljust(left) + value.rjust(right) + (" " * gutter) + "|"

    def centered(text: str) -> str:
        return "|" + text.center(_DASH_WIDTH) + "|"

    border = "+" + ("-" * _DASH_WIDTH) + "+"
    total = report.total or 1
    lines = [
        border,
        centered("VALENCE PIPELINE  //  STAGE 3"),
        centered("Candidate Hydrator  ::  Fuzz Distribution"),
        border,
        metric("Profiles generated", f"{report.total:,}"),
        metric("Negative / impossible ages", f"{report.negative_ages:,} ({report.negative_ages / total * 100:.1f}%)"),
        metric("Unauthorized channels", f"{report.unauthorized_channels:,} ({report.unauthorized_channels / total * 100:.1f}%)"),
        metric("Historical era anomalies", f"{report.era_anomalies:,} ({report.era_anomalies / total * 100:.1f}%)"),
        border,
    ]
    return "\n".join(lines)


def _run_scale_validation() -> None:
    """Generate 10,000 profiles and drive them through Stage 4 at scale."""
    from stage4_razor_reranker import (
        MAX_BATCH_SIZE,
        InsufficientEligibleCandidatesError,
        RazorReranker,
        _default_context,
    )

    profiles = FuzzDataGenerator(seed=1337).generate(10_000)
    for profile in profiles:
        assert set(profile.keys()) == {
            "id",
            "age",
            "anniversary",
            "channel",
            "colorway",
            "era_year",
        }, "generated profile shape must match the Stage 4 schema"

    context = _default_context()

    def run_pipeline() -> list[str]:
        engine = RazorReranker()
        winners: list[str] = []
        for batch in batched(profiles, MAX_BATCH_SIZE):
            if len(batch) < 5:
                continue
            try:
                result = engine.rerank(batch, context)
            except InsufficientEligibleCandidatesError:
                continue
            for candidate in result.selected:
                winners.append(candidate.id)
                assert candidate.channel in context.authorized_channels, "unauthorized actor leaked"
                assert 0 <= candidate.age <= 120, "structurally anomalous age leaked"
        return winners

    first = run_pipeline()
    second = run_pipeline()
    assert first == second, "Stage 4 output must be identical across identical runs"
    assert len(first) > 0, "scale run produced no winners"


def main() -> int:
    generator = FuzzDataGenerator(seed=1337)
    generator.generate(10_000)
    print()
    print(render_dashboard(generator.report))
    print()
    _run_scale_validation()
    print("  Stage 3 fuzz generation and Stage 4 scale validation passed.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
