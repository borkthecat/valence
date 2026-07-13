from shadow_readiness_gate import evaluate_gate
from shadow_operations import ShadowInput, ShadowStore


def test_shadow_gate_passes_complete_reviewed_evidence() -> None:
    result = evaluate_gate({
        "classified_comparisons": 1_000,
        "review_precision": 0.96,
        "review_recall": 0.97,
        "comparison_agreement": 0.98,
        "latency_ms": {"p95": 150},
    })
    assert result["passed"] is True


def test_shadow_gate_fails_unmeasured_evidence() -> None:
    result = evaluate_gate({
        "classified_comparisons": 0,
        "review_precision": "unmeasured",
        "review_recall": "unmeasured",
        "comparison_agreement": "unmeasured",
        "latency_ms": {"p95": "unmeasured"},
    })
    assert result["passed"] is False
    assert not any(result["checks"].values())


def test_shadow_report_computes_review_metrics(tmp_path) -> None:
    store = ShadowStore(tmp_path / "shadow.sqlite")
    item = ShadowInput(
        tenant_id="tenant", source_event_id="event", case_id="case",
        job_digest="job", candidate_set_digest="candidates", input_schema_version="1",
        model_version="model", model_digest="model-digest", policy_version="policy",
        policy_digest="policy-digest", advisory_output={}, advisory_output_digest="output",
        latency_ms=42, trace_id="trace",
    )
    run = store.submit(item, "idempotency")
    run = store.outcome("tenant", run["shadow_run_id"], {"review_required": True}, run["version"])
    store.compare("tenant", run["shadow_run_id"], {
        "match": True,
        "predicted_review_required": True,
        "actual_review_required": True,
    }, run["version"])
    report = store.report("tenant")
    assert report["review_precision"] == 1.0
    assert report["review_recall"] == 1.0
    assert report["latency_ms"] == {"p50": 42.0, "p95": 42.0, "p99": 42.0}
