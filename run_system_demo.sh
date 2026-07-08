#!/usr/bin/env bash

set -euo pipefail

COMPOSE=(docker compose --profile enterprise -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example)
KAFKA_TOPICS=/opt/kafka/bin/kafka-topics.sh

run_bounded() {
  local seconds="$1"
  shift
  timeout --foreground "${seconds}s" "$@"
}

echo "Booting Valence enterprise streaming stack..."
run_bounded 120 "${COMPOSE[@]}" down -v
run_bounded 480 "${COMPOSE[@]}" build
run_bounded 120 "${COMPOSE[@]}" up -d kafka redis

echo "Waiting for Kafka..."
for _ in {1..45}; do
  if "${COMPOSE[@]}" exec -T kafka "$KAFKA_TOPICS" --bootstrap-server kafka:9092 --list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${COMPOSE[@]}" exec -T kafka "$KAFKA_TOPICS" --bootstrap-server kafka:9092 --list >/dev/null

echo "Creating ingestion topic..."
"${COMPOSE[@]}" exec -T kafka "$KAFKA_TOPICS" \
  --bootstrap-server kafka:9092 \
  --create \
  --topic valence-raw-profiles \
  --partitions 3 \
  --replication-factor 1 \
  --if-not-exists

"${COMPOSE[@]}" exec -T kafka "$KAFKA_TOPICS" \
  --bootstrap-server kafka:9092 \
  --create \
  --topic valence-profile-dlq \
  --partitions 3 \
  --replication-factor 1 \
  --if-not-exists

echo "Starting gateway, API dashboard, and stream worker..."
run_bounded 120 "${COMPOSE[@]}" up -d gateway pipeline pipeline-worker

echo "Waiting for gateway..."
for _ in {1..90}; do
  if curl -sf http://localhost:8080/healthz >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf http://localhost:8080/healthz >/dev/null

echo "Posting sample enterprise ingest batch..."
curl -sf -X POST http://localhost:8080/api/v1/ingest \
  -H "Content-Type: application/json" \
  -H "x-valence-key: replace-with-a-random-32-plus-character-secret" \
  -d '{
    "batch_id": "batch_enterprise_991",
    "tenant_id": "tenant_corporate_alpha",
    "profiles": [
      {
        "candidate_id": "c1",
        "entity_type": "product",
        "title": "Verified limited edition midnight sapphire watch",
        "description": "Authenticated seller record with matching model, serial evidence, provenance, and image hashes.",
        "age": 34,
        "retail_channel": "direct",
        "era": "1500",
        "colorway": "midnight-sapphire",
        "anniversary": true,
        "raw_score": 94.2,
        "attributes": {"brand": "Arai", "model": "Nanami 1500", "condition": "new", "region": "SG"},
        "signals": {"seller_trust": 0.98, "price_deviation": 0.04, "serial_match": 1},
        "images": [
          {
            "url": "https://cdn.example.test/products/c1-front.webp",
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "mime_type": "image/webp",
            "source": "seller-upload",
            "width": 1600,
            "height": 1200,
            "bytes": 245760
          }
        ]
      },
      {"candidate_id": "c2", "entity_type": "product", "title": "Authorized graphite watch listing", "description": "Authorized boutique record with matching catalog attributes and seller score.", "age": 35, "retail_channel": "brand-direct", "era": "1501", "colorway": "graphite-slate", "raw_score": 91.1, "attributes": {"brand": "Arai", "condition": "new"}, "signals": {"seller_trust": 0.94}},
      {"candidate_id": "c3", "age": 29, "retail_channel": "certified-partner", "era": "1502", "raw_score": 87.0},
      {"candidate_id": "c4", "age": 41, "retail_channel": "boutique-authorized", "era": "1498", "raw_score": 89.5},
      {"candidate_id": "c5", "age": 22, "retail_channel": "direct", "era": "1500", "raw_score": 90.0},
      {"candidate_id": "c6", "age": -5, "retail_channel": "unauthorized", "era": "anomaly", "raw_score": 12.1}
    ]
  }'

echo
echo "Waiting for stream worker verification..."
for _ in {1..30}; do
  if "${COMPOSE[@]}" logs --tail=160 pipeline-worker | grep -q "processed batch batch_enterprise_991"; then
    echo "Enterprise ingest accepted and processed."
    "${COMPOSE[@]}" logs --tail=80 pipeline-worker | grep -E "ValenceStreamWorker|processed batch" || true
    exit 0
  fi
  sleep 1
done

echo "Enterprise ingest was accepted, but the worker did not confirm processing in time."
"${COMPOSE[@]}" logs --tail=160 pipeline-worker
exit 1
