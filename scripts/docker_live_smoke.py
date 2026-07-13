"""Cross-platform live smoke for the production Compose topology."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any


def request_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("content-type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            content_type = response.headers.get_content_type()
            if not raw:
                parsed: Any = None
            elif content_type == "application/json":
                parsed = json.loads(raw)
            else:
                parsed = raw.decode("utf-8", "replace")
            return response.status, parsed
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def wait_for(url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, _ = request_json(url)
            if status == 200:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            error = exc
        time.sleep(1)
    raise TimeoutError(f"service did not become ready: {url}; last error: {error}")


def run(gateway: str, pipeline: str, key: str, timeout_seconds: float) -> dict[str, Any]:
    wait_for(f"{gateway}/healthz", timeout_seconds)
    wait_for(pipeline, timeout_seconds)
    status, smoke = request_json(f"{pipeline}/v1/valence/system/smoke", method="POST", payload={})
    if status != 200 or smoke.get("status") != "pass":
        raise RuntimeError(f"pipeline smoke failed: status={status}, response={smoke}")

    execution_id = uuid.uuid4().hex
    auth = {"x-valence-key": key, "idempotency-key": f"docker-live-shadow-{execution_id}"}
    shadow = {
        "tenant_id": "api-key",
        "source_event_id": f"docker-live-event-{execution_id}",
        "case_id": f"docker-live-case-{execution_id}",
        "job_digest": "sha256:job",
        "candidate_set_digest": "sha256:candidates",
        "input_schema_version": "1.1",
        "model_version": "docker-live",
        "model_digest": "sha256:model",
        "policy_version": "docker-live",
        "policy_digest": "sha256:policy",
        "advisory_output": {"mode": "shadow"},
        "advisory_output_digest": "sha256:advisory",
        "latency_ms": 1.0,
        "trace_id": "docker-live-trace-1",
    }
    status, created = request_json(f"{gateway}/v1/shadow-runs", "POST", shadow, auth)
    if status != 200:
        raise RuntimeError(f"gateway shadow submission failed: status={status}, response={created}")
    run_id = created["shadow_run_id"]
    status, outcome = request_json(
        f"{gateway}/v1/shadow-runs/{run_id}/outcome",
        "POST",
        {"version": created["version"], "outcome": {"decision": "advance"}},
        {"x-valence-key": key},
    )
    if status != 200 or outcome["status"] != "outcome_pending":
        raise RuntimeError(f"gateway shadow outcome failed: status={status}, response={outcome}")
    status, report = request_json(f"{gateway}/v1/shadow-runs/report", headers={"x-valence-key": key})
    if status != 200 or report["total_cases"] < 1:
        raise RuntimeError(f"gateway shadow report failed: status={status}, response={report}")
    return {
        "status": "pass",
        "pipeline_checks": len(smoke["checks"]),
        "shadow_run_id": run_id,
        "shadow_total_cases": report["total_cases"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--pipeline", default="http://127.0.0.1:8090")
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    key = os.environ.get("GATEWAY_API_KEY", "replace-with-a-random-32-plus-character-secret")
    result = run(args.gateway, args.pipeline, key, args.timeout_seconds)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
