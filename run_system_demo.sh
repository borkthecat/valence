#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="$ROOT_DIR/gateway"
PIPELINE_DIR="$ROOT_DIR/pipeline"

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "error: python3 is required but was not found on PATH" >&2
  exit 1
fi

if [[ -f "$ROOT_DIR/.env" ]]; then
  echo "Loading environment from .env"
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

export GATEWAY_PORT="${GATEWAY_PORT:-8080}"
export UPSTREAM_PROVIDER_URL="${UPSTREAM_PROVIDER_URL:-http://127.0.0.1:9}"
export UPSTREAM_API_KEY="${UPSTREAM_API_KEY:-demo-upstream-key-0123456789}"
export GATEWAY_API_KEY="${GATEWAY_API_KEY:-demo-gateway-key-0123456789abcdef0123}"
export SECURITY_MODE="${SECURITY_MODE:-FAIL_CLOSED}"
export MAX_PAYLOAD_KB="${MAX_PAYLOAD_KB:-512}"
export NODE_ENV="${NODE_ENV:-production}"

GATEWAY_PID=""
cleanup() {
  if [[ -n "$GATEWAY_PID" ]] && kill -0 "$GATEWAY_PID" 2>/dev/null; then
    echo "Stopping gateway (pid $GATEWAY_PID)"
    kill "$GATEWAY_PID" 2>/dev/null || true
    wait "$GATEWAY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "== Building gateway =="
(
  cd "$GATEWAY_DIR"
  if [[ ! -d node_modules ]]; then
    npm ci --silent
  fi
  npm run build --silent
)

echo "== Starting gateway on port $GATEWAY_PORT =="
( cd "$GATEWAY_DIR" && node dist/app.js ) &
GATEWAY_PID=$!

echo -n "Waiting for gateway health"
for _ in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$GATEWAY_PORT/healthz" >/dev/null 2>&1; then
    echo " ... ready"
    break
  fi
  echo -n "."
  sleep 0.5
done
curl -sf "http://127.0.0.1:$GATEWAY_PORT/healthz" >/dev/null 2>&1 \
  || { echo " gateway did not become healthy" >&2; exit 1; }

echo
echo "== Stage 3: fuzz generation and scale validation =="
( cd "$PIPELINE_DIR" && "$PYTHON" -W error stage3_hydrator.py )

echo "== Stage 4: deterministic reranking =="
( cd "$PIPELINE_DIR" && "$PYTHON" -W error stage4_razor_reranker.py )

echo "== Stage 5: concurrent cognitive verification =="
( cd "$PIPELINE_DIR" && "$PYTHON" -W error stage5_cognitive_verifier.py )

echo
echo "System demo complete."
