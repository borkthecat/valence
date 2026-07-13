"""Signed identity verification for gateway-to-internal-service requests."""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict


class InternalActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    tenant_id: str
    scopes: frozenset[str]


def actor_dependency(key: str):
    if len(key) < 32:
        raise RuntimeError("internal service key must contain at least 32 characters")

    async def actor(
        request: Request,
        actor_id: str = Header(..., alias="X-Valence-Actor"),
        tenant: str = Header(..., alias="X-Valence-Tenant"),
        scopes: str = Header(..., alias="X-Valence-Scopes"),
        timestamp: str = Header(..., alias="X-Valence-Internal-Timestamp"),
        signature: str = Header(..., alias="X-Valence-Internal-Signature"),
        request_id: str = Header(..., alias="X-Request-Id"),
        trace_id: str = Header(..., alias="X-Trace-Id"),
    ) -> InternalActor:
        try:
            body = await request.body()
            digest = hashlib.sha256(body).hexdigest()
            canonical = "\n".join(
                (
                    timestamp,
                    request.method,
                    request.url.path,
                    tenant,
                    actor_id,
                    scopes,
                    request_id,
                    trace_id,
                    digest,
                )
            )
            expected = hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
            observed_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if not hmac.compare_digest(expected, signature):
                raise ValueError("signature mismatch")
            if abs((datetime.now(UTC) - observed_at).total_seconds()) > 300:
                raise ValueError("stale signature")
        except (ValueError, TypeError):
            raise HTTPException(401, "internal authentication failed") from None
        return InternalActor(
            actor_id=actor_id,
            tenant_id=tenant,
            scopes=frozenset(scopes.split()),
        )

    return actor


def require_scope(actor: InternalActor, scope: str, admin_scope: str) -> None:
    if scope not in actor.scopes and admin_scope not in actor.scopes:
        raise HTTPException(403, "insufficient scope")
