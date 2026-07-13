from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from review_operations import CreateReview, ReviewStore, create_app


def _task(tenant: str = "tenant-a") -> CreateReview:
    return CreateReview(tenant_id=tenant, case_id="case-1", candidate_id="candidate-1", source_request_id="request-1", policy_version="p1", model_version="m1", model_digest="digest", evidence_snapshot_digest="evidence", risk="low")


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
    }
    assert client.post("/v1/reviews", content=body, headers=headers).status_code == 401
    canonical = "\n".join((timestamp, "POST", "/v1/reviews", "tenant-a", "reviewer-a", "review:claim", "request-1", "trace-1", hashlib.sha256(body).hexdigest()))
    headers["X-Valence-Internal-Signature"] = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    headers["Idempotency-Key"] = "signed-key"
    response = client.post("/v1/reviews", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
