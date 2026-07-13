from pii_release_gate import evaluate_gate


LABELS = ("EMAIL", "PHONE", "SSN", "CREDIT_CARD", "IP_ADDRESS", "API_KEY", "PASSWORD")


def report(*, coverage: float = 0.95, precision: float = 0.96, recall: float = 0.96) -> dict:
    return {
        "labelCoverage": coverage,
        "exactSpanMetricsOnSupportedLabels": {"precision": precision, "recall": recall},
        "perLabel": {label: {"recall": 0.90} for label in LABELS},
    }


def test_pii_gate_passes_complete_exact_span_evidence() -> None:
    assert evaluate_gate(report())["passed"] is True


def test_pii_gate_rejects_narrow_taxonomy_even_with_good_supported_metrics() -> None:
    result = evaluate_gate(report(coverage=0.25))
    assert result["passed"] is False
    assert result["checks"]["taxonomy_coverage"] is False
