from __future__ import annotations

import json
import sqlite3
import hashlib
import hmac
import importlib
from contextlib import closing
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from benchmarks.external_provider_cache import ExternalProviderCache
from benchmarks.rdap_domain_evidence import BOOTSTRAP_URL, RdapDomainEvidenceProvider
from fairness_invariants import assert_decision_invariance
from operations_metrics import operational_report
from operations_recovery import restore_databases, run_recovery_drill
from policy_registry import PolicyRegistry
from review_operations import CreateReview, ReviewStore
from shadow_operations import ShadowInput, ShadowStore
from talent_adapters import adapt


def test_csv_json_and_jsonl_adapters_are_canonical(tmp_path) -> None:
    records = [{"case_id": "c", "job_id": "j", "candidate_id": "b", "claimed_skills": ["Python", "SQL"]},
               {"case_id": "c", "job_id": "j", "candidate_id": "a", "claimed_skills": "sql; python"}]
    json_path = tmp_path / "input.json"; json_path.write_text(json.dumps(records), encoding="utf-8")
    jsonl_path = tmp_path / "input.jsonl"; jsonl_path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")
    csv_path = tmp_path / "input.csv"; csv_path.write_text("case_id,job_id,candidate_id,claimed_skills\nc,j,b,Python;SQL\nc,j,a,sql;python\n", encoding="utf-8")
    outputs = [adapt(path, source_system="fixture") for path in (json_path, jsonl_path, csv_path)]
    assert {result[1].canonical_digest for result in outputs} == {outputs[0][1].canonical_digest}
    assert all(result[1].records == 2 for result in outputs)


def test_adapter_rejects_duplicate_candidate_identity(tmp_path) -> None:
    path = tmp_path / "input.json"; path.write_text(json.dumps([{"case_id": "c", "job_id": "j", "candidate_id": "a"}] * 2), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        adapt(path, source_system="fixture")


def test_identity_only_mutations_cannot_change_decision() -> None:
    records = [{"candidate_id": "a", "experience": 8, "display_name": "Alice", "email": "a@example.test"}]
    report = assert_decision_invariance(records, lambda item: item["experience"] >= 5)
    assert report.passed and report.pairs == 1
    with pytest.raises(AssertionError, match="identity-only"):
        assert_decision_invariance(records, lambda item: item["display_name"])


def test_policy_registry_activates_and_rolls_back_per_tenant(tmp_path) -> None:
    registry = PolicyRegistry(tmp_path / "policies.sqlite")
    first = registry.stage("tenant-a", "v1", {"threshold": .5}, "admin")
    registry.stage("tenant-a", "v2", {"threshold": .7}, "admin")
    registry.activate("tenant-a", "v2", "admin")
    rolled = registry.rollback("tenant-a", "v1", "admin")
    assert rolled["digest"] == first["digest"] and registry.current("tenant-a")["version"] == "v1"
    assert [event["action"] for event in registry.audit("tenant-a")] == ["staged", "staged", "activated", "rolled_back"]
    with pytest.raises(KeyError): registry.current("tenant-b")


def test_multi_store_recovery_drill_and_manifest_tamper_detection(tmp_path) -> None:
    sources = {"reviews": tmp_path / "reviews.sqlite", "shadow": tmp_path / "shadow.sqlite"}
    for path in sources.values():
        with closing(sqlite3.connect(path)) as db, db: db.execute("CREATE TABLE evidence(value TEXT)"); db.execute("INSERT INTO evidence VALUES('kept')")
    report = run_recovery_drill(sources, tmp_path / "drill")
    assert report.integrity_verified and report.databases == 2
    manifest = tmp_path / "drill" / "backup" / "manifest.json"
    (manifest.parent / "reviews.sqlite").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="manifest verification"):
        restore_databases(manifest, {"reviews": tmp_path / "r.sqlite", "shadow": tmp_path / "s.sqlite"})


def _shadow() -> ShadowInput:
    return ShadowInput(tenant_id="t", source_event_id="e", case_id="c", job_digest="j", candidate_set_digest="cs", input_schema_version="1", model_version="m", model_digest="md", policy_version="p", policy_digest="pd", advisory_output={}, advisory_output_digest="o", latency_ms=42, token_usage=10, provider_cost=.01, trace_id="tr")


def test_operational_report_is_payload_free_and_detects_volume_drift(tmp_path) -> None:
    reviews, shadows = tmp_path / "reviews.sqlite", tmp_path / "shadow.sqlite"
    ReviewStore(reviews).create(CreateReview(tenant_id="t", case_id="c", candidate_id="x", source_request_id="s", trace_id="tr", policy_version="p", model_version="m", model_digest="d", evidence_snapshot_digest="e", advisory_output_digest="a", risk="low"), "k")
    ShadowStore(shadows).submit(_shadow(), "k")
    report = operational_report(reviews, shadows, "t", baseline_volume=2)
    assert report["latency_ms"] == {"p50": 42.0, "p95": 42.0, "p99": 42.0}
    assert report["volume_drift_alert"] and not report["production_slo_certified"]
    assert "payload" not in json.dumps(report)


def test_signed_operations_metrics_route(tmp_path, monkeypatch) -> None:
    key = "k" * 32; path = "/v1/operations/metrics"; timestamp = datetime.now(UTC).isoformat()
    monkeypatch.setenv("VALENCE_REVIEW_INTERNAL_KEY", key)
    build_app = importlib.import_module("operations_service").build_app
    canonical = "\n".join((timestamp, "GET", path, "t", "operator", "operations:read", "req", "trace", hashlib.sha256(b"").hexdigest()))
    headers = {"X-Valence-Actor": "operator", "X-Valence-Tenant": "t", "X-Valence-Scopes": "operations:read", "X-Request-Id": "req", "X-Trace-Id": "trace", "X-Valence-Internal-Timestamp": timestamp, "X-Valence-Internal-Signature": hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()}
    response = TestClient(build_app(tmp_path, key)).get(path, headers=headers)
    assert response.status_code == 200 and response.json()["production_slo_certified"] is False


def test_rdap_provider_uses_bootstrap_and_extracts_domain_age(tmp_path) -> None:
    calls = []
    def fetch(url: str, timeout: float) -> dict:
        calls.append(url)
        if url == BOOTSTRAP_URL: return {"services": [[["com"], ["https://rdap.example/"]]]}
        return {"objectClassName": "domain", "events": [{"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"}], "status": ["active"], "nameservers": [{"ldhName": "NS1.EXAMPLE"}]}
    provider = RdapDomainEvidenceProvider(ExternalProviderCache(tmp_path / "cache.sqlite", minimum_interval_seconds=0), fetch_json=fetch, now=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    evidence = provider.lookup("Example.COM")
    assert evidence["status"] == "found" and evidence["domain_age_days"] == 2192 and evidence["nameserver_count"] == 1
    assert provider.lookup("example.com") == evidence and len(calls) == 2
