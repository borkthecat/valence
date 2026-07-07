#!/usr/bin/env python3

from __future__ import annotations

import random
from hashlib import sha256
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from config import get_settings

NEGATIVE_AGE_RATE: Final[float] = 0.05
UNAUTHORIZED_CHANNEL_RATE: Final[float] = 0.05
ERA_ANOMALY_RATE: Final[float] = 0.10
COMPLEX_PROFILE_RATE: Final[float] = 0.15
DEFAULT_SCALE_VALIDATION_PROFILE_COUNT: Final[int] = 2_000_000
DEFAULT_SCALE_VALIDATION_WINDOW: Final[int] = 100_000

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

    negative_age: bool
    unauthorized_channel: bool
    era_anomaly: bool
    complex_profile: bool


@dataclass(slots=True)
class GenerationReport:
    total: int
    negative_ages: int
    unauthorized_channels: int
    era_anomalies: int
    complex_profiles: int


@dataclass(frozen=True, slots=True)
class ScaleValidationReport:
    profiles: int
    windows: int
    batches: int
    winners: int
    fingerprint: str


class FuzzDataGenerator:

    def __init__(self, seed: int | None = 1337) -> None:
        self._rng = random.Random(seed)
        self._settings = get_settings()
        self._authorized = tuple(sorted(self._settings.authorized_channels))
        self._report = GenerationReport(0, 0, 0, 0, 0)

    @property
    def report(self) -> GenerationReport:
        return self._report

    def generate(self, count: int, start_index: int = 0) -> list[dict[str, Any]]:
        if count <= 0:
            raise ValueError("count must be positive")
        self._report = GenerationReport(count, 0, 0, 0, 0)
        profiles: list[dict[str, Any]] = []
        for index in range(start_index, start_index + count):
            profiles.append(self._generate_one(index))
        return profiles

    def _generate_one(self, index: int) -> dict[str, Any]:
        rng = self._rng
        if rng.random() < COMPLEX_PROFILE_RATE:
            profile = self._generate_complex_one(index)
            self._record_profile(profile, complex_profile=True)
            return profile

        target_era = self._settings.target_era

        if rng.random() < NEGATIVE_AGE_RATE:
            age: float = float(rng.choice([-rng.randint(1, 40), rng.randint(121, 400)]))
        else:
            age = float(rng.randint(1, 75))

        if rng.random() < UNAUTHORIZED_CHANNEL_RATE:
            channel = rng.choice(_UNAUTHORIZED_CHANNELS)
        else:
            channel = rng.choice(self._authorized)

        if rng.random() < ERA_ANOMALY_RATE:
            offset = rng.randint(101, 400) * rng.choice((-1, 1))
            era_year = target_era + offset
        else:
            era_year = target_era + rng.randint(-30, 30)

        profile = {
            "id": f"fuzz-{index:06d}",
            "age": age,
            "anniversary": bool(rng.getrandbits(1)),
            "channel": channel,
            "colorway": rng.choice(_COLORWAYS),
            "era_year": era_year,
        }
        self._record_profile(profile, complex_profile=False)
        return profile

    def _generate_complex_one(self, index: int) -> dict[str, Any]:
        target_era = self._settings.target_era
        target_channel = self._settings.target_channel
        target_colorway = self._settings.target_colorway
        authorized_alt = self._authorized[index % len(self._authorized)]
        archetype = index % 8

        if archetype == 0:
            age, channel, colorway, era_year = 0.0, target_channel, target_colorway.upper(), target_era
        elif archetype == 1:
            age, channel, colorway, era_year = 120.0, authorized_alt, f" {target_colorway} ", target_era + 100
        elif archetype == 2:
            age, channel, colorway, era_year = 80.1, target_channel, "graphite-slate", target_era + 51
        elif archetype == 3:
            age, channel, colorway, era_year = 26.5, _UNAUTHORIZED_CHANNELS[index % len(_UNAUTHORIZED_CHANNELS)], target_colorway, target_era
        elif archetype == 4:
            age, channel, colorway, era_year = -1.0, target_channel, target_colorway, target_era
        elif archetype == 5:
            age, channel, colorway, era_year = 37.0, authorized_alt, target_colorway.swapcase(), target_era + 101
        elif archetype == 6:
            age, channel, colorway, era_year = 119.9, target_channel, target_colorway, target_era - 50
        else:
            age, channel, colorway, era_year = 81.0, authorized_alt, "crimson-ember", target_era - 100

        return {
            "id": f"fuzz-{index:06d}",
            "age": age,
            "anniversary": bool((index // 8) % 2),
            "channel": channel,
            "colorway": colorway,
            "era_year": era_year,
        }

    def _record_profile(self, profile: dict[str, Any], complex_profile: bool) -> None:
        target_era = self._settings.target_era
        age = float(profile["age"])
        channel = str(profile["channel"])
        era_year = int(profile["era_year"])

        if age < 0 or age > 120:
            self._report.negative_ages += 1
        if channel not in self._authorized:
            self._report.unauthorized_channels += 1
        if abs(era_year - target_era) > 100:
            self._report.era_anomalies += 1
        if complex_profile:
            self._report.complex_profiles += 1


def batched(items: list[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    if size <= 0:
        raise ValueError("size must be positive")
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _add_report(left: GenerationReport, right: GenerationReport) -> GenerationReport:
    return GenerationReport(
        total=left.total + right.total,
        negative_ages=left.negative_ages + right.negative_ages,
        unauthorized_channels=left.unauthorized_channels + right.unauthorized_channels,
        era_anomalies=left.era_anomalies + right.era_anomalies,
        complex_profiles=left.complex_profiles + right.complex_profiles,
    )


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
        metric("Complex adversarial profiles", f"{report.complex_profiles:,} ({report.complex_profiles / total * 100:.1f}%)"),
        border,
    ]
    return "\n".join(lines)


def _scale_settings() -> tuple[int, int]:
    settings = get_settings()
    profiles = settings.scale_validation_profiles
    window = settings.scale_validation_window
    if profiles < 1_000_000:
        raise ValueError("VALENCE_SCALE_VALIDATION_PROFILES must be >= 1000000")
    if window < 1_000 or window > profiles:
        raise ValueError("VALENCE_SCALE_VALIDATION_WINDOW must be between 1000 and profile count")
    return profiles, window


def _run_scale_pass(profile_count: int, window_size: int) -> ScaleValidationReport:
    from stage4_razor_reranker import (
        MAX_BATCH_SIZE,
        InsufficientEligibleCandidatesError,
        RazorReranker,
        _default_context,
    )

    context = _default_context()
    digest = sha256()
    windows = 0
    batches = 0
    winners = 0

    for start in range(0, profile_count, window_size):
        count = min(window_size, profile_count - start)
        generator = FuzzDataGenerator(seed=1337 + windows)
        profiles = generator.generate(count, start_index=start)
        engine = RazorReranker()
        windows += 1

        for profile in profiles:
            assert set(profile.keys()) == {
                "id",
                "age",
                "anniversary",
                "channel",
                "colorway",
                "era_year",
            }, "generated profile shape must match the Stage 4 schema"

        for batch in batched(profiles, MAX_BATCH_SIZE):
            if len(batch) < 5:
                continue
            batches += 1
            try:
                result = engine.rerank(batch, context)
            except InsufficientEligibleCandidatesError:
                continue
            for candidate in result.selected:
                winners += 1
                assert candidate.channel in context.authorized_channels, "unauthorized actor leaked"
                assert 0 <= candidate.age <= 120, "structurally anomalous age leaked"
                digest.update(candidate.id.encode("ascii"))
                digest.update(b"\0")

    return ScaleValidationReport(
        profiles=profile_count,
        windows=windows,
        batches=batches,
        winners=winners,
        fingerprint=digest.hexdigest(),
    )


def _run_scale_validation() -> ScaleValidationReport:
    profile_count, window_size = _scale_settings()
    first = _run_scale_pass(profile_count, window_size)
    second = _run_scale_pass(profile_count, window_size)
    assert first.fingerprint == second.fingerprint, "Stage 4 output must be identical across identical runs"
    assert first.winners == second.winners, "winner count changed across identical runs"
    assert first.winners > 0, "scale run produced no winners"
    return first


def main() -> int:
    profile_count, window_size = _scale_settings()
    aggregate = GenerationReport(0, 0, 0, 0, 0)
    for window, start in enumerate(range(0, profile_count, window_size)):
        count = min(window_size, profile_count - start)
        generator = FuzzDataGenerator(seed=1337 + window)
        generator.generate(count, start_index=start)
        aggregate = _add_report(aggregate, generator.report)
    print()
    print(render_dashboard(aggregate))
    print()
    report = _run_scale_validation()
    print(
        "  Stage 3 staggered generation and Stage 4 scale validation passed "
        f"({report.profiles:,} profiles, {report.windows:,} windows, "
        f"{report.batches:,} batches)."
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
