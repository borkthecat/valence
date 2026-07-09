from __future__ import annotations

import json
import sys
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parents[1] / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))

from injection_corpora import SPECS, _deterministic_split, fingerprint, policy_text
from run_injection_matrix import _result


def test_registry_has_fifteen_unique_pinned_corpora() -> None:
    assert len(SPECS) == 15
    assert len({spec.name for spec in SPECS}) == 15
    assert all(len(spec.revision) == 40 for spec in SPECS)
    assert all(spec.license in {"Apache-2.0", "MIT"} for spec in SPECS)
    assert {spec.policy for spec in SPECS} == {"direct", "indirect", "secret"}


def test_deterministic_split_is_balanced_and_disjoint() -> None:
    rows = [(f"benign {index}", False) for index in range(20)]
    rows += [(f"attack {index}", True) for index in range(20)]
    training, test = _deterministic_split(rows)
    assert len(training) == 32
    assert len(test) == 8
    assert sum(label for _, label in test) == 4
    assert {fingerprint(text) for text, _ in training}.isdisjoint(
        {fingerprint(text) for text, _ in test},
    )
    assert _deterministic_split(rows) == (training, test)


def test_matrix_parser_ignores_npm_prefix() -> None:
    payload = {"benchmark": "prompt-injection", "metrics": {"accuracy": 1}}
    output = "> package@1.0 benchmark\n> tsx benchmark.ts\n\n" + json.dumps(payload, indent=2)
    assert _result(output) == payload


def test_policy_context_is_explicit_and_validated() -> None:
    assert policy_text("hello", "indirect") == "[VALENCE_CONTEXT=indirect] hello"
    try:
        policy_text("hello", "unknown")
    except ValueError as error:
        assert "unsupported guard policy" in str(error)
    else:
        raise AssertionError("unknown policy was accepted")
