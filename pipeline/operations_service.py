"""Combined local-mode review and shadow operations service."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from internal_service_auth import InternalActor, actor_dependency, require_scope
from operations_metrics import operational_report
from policy_registry import PolicyRegistry
from review_operations import ReviewStore, create_router as create_review_router
from shadow_operations import ShadowStore, create_router as create_shadow_router


class PolicyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=128)
    document: dict


def build_app(
    database_dir: str | Path | None = None,
    internal_key: str | None = None,
) -> FastAPI:
    root = Path(database_dir or os.environ.get("VALENCE_OPERATIONS_DB_DIR", ".valence-data"))
    root.mkdir(parents=True, exist_ok=True)
    key = internal_key or os.environ.get("VALENCE_REVIEW_INTERNAL_KEY")
    app = FastAPI(title="Valence Operations", version="1.0")
    review_store = ReviewStore(root / "reviews.sqlite")
    shadow_store = ShadowStore(root / "shadow.sqlite")
    policy_store = PolicyRegistry(root / "policies.sqlite")
    app.include_router(create_review_router(review_store, key))
    app.include_router(create_shadow_router(shadow_store, key))
    if key is None or len(key) < 32:
        raise RuntimeError("VALENCE_REVIEW_INTERNAL_KEY must be configured with at least 32 characters")
    actor = actor_dependency(key)

    @app.post("/v1/policies")
    def stage_policy(item: PolicyDocument, identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "policy:write", "policy:admin")
        try:
            return policy_store.stage(identity.tenant_id, item.version, item.document, identity.actor_id)
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "policy version already exists") from error

    @app.post("/v1/policies/{version}/activate")
    def activate_policy(version: str, identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "policy:activate", "policy:admin")
        try: return policy_store.activate(identity.tenant_id, version, identity.actor_id)
        except KeyError: raise HTTPException(404, "policy version not found")

    @app.post("/v1/policies/{version}/rollback")
    def rollback_policy(version: str, identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "policy:rollback", "policy:admin")
        try: return policy_store.rollback(identity.tenant_id, version, identity.actor_id)
        except KeyError: raise HTTPException(404, "policy version not found")

    @app.get("/v1/policies/current")
    def current_policy(identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "policy:read", "policy:admin")
        try: return policy_store.current(identity.tenant_id)
        except KeyError: raise HTTPException(404, "active policy not found")

    @app.get("/v1/policies/audit")
    def policy_audit(identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "policy:audit", "policy:admin")
        return {"events": policy_store.audit(identity.tenant_id)}

    @app.get("/v1/operations/metrics")
    def metrics(baseline_volume: int | None = Query(default=None, ge=0), identity: InternalActor = Depends(actor)) -> dict:
        require_scope(identity, "operations:read", "operations:admin")
        return operational_report(root / "reviews.sqlite", root / "shadow.sqlite", identity.tenant_id, baseline_volume=baseline_volume)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = build_app()
