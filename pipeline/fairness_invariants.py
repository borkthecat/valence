"""Controlled metamorphic checks for decision-irrelevant identity fields.

These checks detect regressions; they are not a fairness certification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

PROTECTED_NON_DECISION_FIELDS = frozenset({"display_name", "email", "phone", "pronouns"})


@dataclass(frozen=True, slots=True)
class InvariantReport:
    pairs: int
    violations: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.violations


def assert_decision_invariance(
    records: list[dict[str, Any]], scorer: Callable[[dict[str, Any]], Any]
) -> InvariantReport:
    violations: list[str] = []
    for index, original in enumerate(records):
        mutated = dict(original)
        for field in PROTECTED_NON_DECISION_FIELDS:
            if field in mutated:
                mutated[field] = f"invariant-{field}-{index}"
        if scorer(original) != scorer(mutated):
            violations.append(str(original.get("candidate_id", index)))
    report = InvariantReport(len(records), tuple(violations))
    if not report.passed:
        raise AssertionError(f"decision changed for identity-only mutation: {report.violations}")
    return report
