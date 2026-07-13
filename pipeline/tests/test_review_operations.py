from __future__ import annotations

from review_operations import CreateReview, ReviewStore


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
