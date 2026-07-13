from __future__ import annotations

import hashlib
import hmac
import json
import warnings
from datetime import UTC, datetime

warnings.filterwarnings("ignore", category=DeprecationWarning, message="Using `httpx` with `starlette.testclient` is deprecated.*")
from fastapi.testclient import TestClient

from review_operations import CreateReview, ReviewStore, create_app
from shadow_operations import ShadowStore
from stage5_cognitive_verifier import CandidateJudgment, CandidateProfile, CandidateReview, PolicyOutcome, Stage5Request, StructuredReview, configure_review_task_store, configure_shadow_store, persist_review_tasks, persist_shadow_run


def _task(tenant: str = "tenant-a") -> CreateReview:
    return CreateReview(tenant_id=tenant, case_id="case-1", candidate_id="candidate-1", source_request_id="request-1", trace_id="trace-1", policy_version="p1", model_version="m1", model_digest="digest", evidence_snapshot_digest="evidence", advisory_output_digest="advisory", risk="low")


def test_review_store_is_idempotent_and_tenant_scoped(tmp_path) -> None:
    store = ReviewStore(tmp_path / "reviews.db")
    first = store.create(_task(), "key-1")
    assert store.create(_task(), "key-1")["review_id"] == first["review_id"]
    claimed = store.transition("tenant-a", first["review_id"], "reviewer-a", "claim", 1)
    assert claimed["status"] == "claimed"
    assert len(store.audit("tenant-a", first["review_id"])) == 2
    try:
        store.get("tenant-b", first["review_id"])
    except KeyError:
        pass
    else:
        raise AssertionError("cross-tenant access must fail")


def test_review_store_rejects_stale_versions(tmp_path) -> None:
    store = ReviewStore(tmp_path / "reviews.db")
    review = store.create(_task(), "key-1")
    store.transition("tenant-a", review["review_id"], "reviewer-a", "claim", 1)
    try:
        store.transition("tenant-a", review["review_id"], "reviewer-a", "decision", 1, "advance")
    except ValueError as error:
        assert "version conflict" in str(error)
    else:
        raise AssertionError("stale update must fail")


def test_review_service_requires_signed_gateway_identity(tmp_path) -> None:
    key = "k" * 32
    client = TestClient(create_app(ReviewStore(tmp_path / "reviews.db"), key))
    payload = _task().model_dump(mode="json")
    assert client.post("/v1/reviews", json=payload).status_code == 422
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = datetime.now(UTC).isoformat()
    headers = {
        "X-Valence-Actor": "reviewer-a",
        "X-Valence-Tenant": "tenant-a",
        "X-Valence-Scopes": "review:claim",
        "X-Request-Id": "request-1",
        "X-Trace-Id": "trace-1",
        "X-Valence-Internal-Timestamp": timestamp,
        "X-Valence-Internal-Signature": "forged",
        "Content-Type": "application/json",
    }
    assert client.post("/v1/reviews", content=body, headers=headers).status_code == 401
    canonical = "\n".join((timestamp, "POST", "/v1/reviews", "tenant-a", "reviewer-a", "review:claim", "request-1", "trace-1", hashlib.sha256(body).hexdigest()))
    headers["X-Valence-Internal-Signature"] = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers["Idempotency-Key"] = "signed-key"
    response = client.post("/v1/reviews", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"


def test_advisory_persists_only_review_required_tasks_idempotently(tmp_path) -> None:
    store = ReviewStore(tmp_path / "reviews.db")
    configure_review_task_store(store)
    request = Stage5Request(tenant_id="tenant-a", target_channel="direct", pool=[
        CandidateProfile(id="candidate-1", age=30, anniversary=False, channel="direct", colorway="blue", era_year=2020),
        CandidateProfile(id="candidate-2", age=30, anniversary=False, channel="direct", colorway="red", era_year=2020),
    ])
    review = StructuredReview(candidates=[
        CandidateReview(candidate_id="candidate-1", model_assessment=CandidateJudgment(candidate_id="candidate-1", eligibility="eligible", evidence_consistency=1, relevance_adjustment=0, recommended_action="shortlist"), policy_outcome=PolicyOutcome(shortlist_eligible=True, human_review_required=False, reason_codes=[])),
        CandidateReview(candidate_id="candidate-2", model_assessment=CandidateJudgment(candidate_id="candidate-2", eligibility="unknown", evidence_consistency=.2, relevance_adjustment=0, recommended_action="hold_for_review"), policy_outcome=PolicyOutcome(shortlist_eligible=False, human_review_required=True, reason_codes=["UNCERTAINTY_MISSING_REQUIRED_EVIDENCE"])),
    ], recommended_shortlist=["candidate-1"], human_review_required=True, mitigation_logs="none")
    first = persist_review_tasks(request, review, "request-1", "trace-1")
    assert len(first) == 1
    assert persist_review_tasks(request, review, "request-1", "trace-1") == first
    assert len(store.list("tenant-a", None, 10, 0)) == 1
    shadow_store = ShadowStore(tmp_path / "shadow.db")
    configure_shadow_store(shadow_store)
    shadow_id = persist_shadow_run(request, review, first, "request-1", "trace-1", 2.5)
    assert shadow_id is not None
    shadow = shadow_store.get("tenant-a", shadow_id)
    assert json.loads(shadow["payload"])["review_task_ids"] == list(first)
    configure_review_task_store(None)
    configure_shadow_store(None)
