"""Structured JSON logging for the Valence pipeline.

Emits machine-readable log records that cloud log processors (Datadog,
Splunk, Google Cloud Logging) can index and alert on. The box-drawn
dashboards remain for human-facing demos; this layer is the ingestion
path. Records go to stderr so they never contaminate a dashboard printed
to stdout, and emission is gated on the VALENCE_JSON_LOGS environment
flag so local runs stay quiet by default.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_ENABLED = os.environ.get("VALENCE_JSON_LOGS", "").lower() in ("1", "true", "yes")


def build_record(
    component: str,
    event: str,
    *,
    level: str = "INFO",
    trace_id: str | None = None,
    stage: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a log record conforming to the platform schema."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level.upper(),
        "component": component,
        "trace_id": trace_id,
        "context": {
            "stage": stage,
            "event": event,
            "metrics": metrics or {},
        },
    }


def log_event(
    component: str,
    event: str,
    *,
    level: str = "INFO",
    trace_id: str | None = None,
    stage: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured record and emit it to stderr when logging is enabled."""
    record = build_record(
        component,
        event,
        level=level,
        trace_id=trace_id,
        stage=stage,
        metrics=metrics,
    )
    if _ENABLED:
        sys.stderr.write(json.dumps(record) + "\n")
    return record
