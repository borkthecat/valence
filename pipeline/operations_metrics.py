"""Payload-free aggregate operational SLO and drift calculations."""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values); index = min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[index], 3)


def operational_report(review_db: Path, shadow_db: Path, tenant: str, *, baseline_volume: int | None = None) -> dict:
    with closing(sqlite3.connect(review_db)) as db:
        review_rows = db.execute("SELECT status,COUNT(*) FROM reviews WHERE tenant=? GROUP BY status", (tenant,)).fetchall()
    with closing(sqlite3.connect(shadow_db)) as db:
        rows = db.execute("SELECT status,payload FROM shadow_runs WHERE tenant=?", (tenant,)).fetchall()
    latencies, costs, tokens = [], 0.0, 0
    for _, raw in rows:
        payload = json.loads(raw); latencies.append(float(payload.get("latency_ms", 0)))
        costs += float(payload.get("provider_cost", 0)); tokens += int(payload.get("token_usage", 0))
    volume = len(rows)
    drift = None if baseline_volume in (None, 0) else round((volume - baseline_volume) / baseline_volume, 6)
    return {
        "tenant_id": tenant,
        "reviews_by_status": dict(review_rows),
        "shadow_runs": volume,
        "shadow_by_status": {status: sum(1 for item, _ in rows if item == status) for status in sorted({item for item, _ in rows})},
        "latency_ms": {"p50": _percentile(latencies, .50), "p95": _percentile(latencies, .95), "p99": _percentile(latencies, .99)},
        "token_usage": tokens, "provider_cost": round(costs, 6),
        "volume_drift_ratio": drift, "volume_drift_alert": drift is not None and abs(drift) > .20,
        "production_slo_certified": False,
    }
