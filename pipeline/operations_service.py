"""Combined local-mode review and shadow operations service."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from review_operations import ReviewStore, create_router as create_review_router
from shadow_operations import ShadowStore, create_router as create_shadow_router


def build_app(
    database_dir: str | Path | None = None,
    internal_key: str | None = None,
) -> FastAPI:
    root = Path(database_dir or os.environ.get("VALENCE_OPERATIONS_DB_DIR", ".valence-data"))
    root.mkdir(parents=True, exist_ok=True)
    key = internal_key or os.environ.get("VALENCE_REVIEW_INTERNAL_KEY")
    app = FastAPI(title="Valence Operations", version="1.0")
    app.include_router(create_review_router(ReviewStore(root / "reviews.sqlite"), key))
    app.include_router(create_shadow_router(ShadowStore(root / "shadow.sqlite"), key))

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = build_app()
