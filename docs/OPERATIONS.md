# Operations, Reliability, and Cost

## Initial SLOs

| Measure | Target |
| --- | ---: |
| Gateway availability | >=99.9% |
| Added latency p50 / p95 / p99 | <30 / <75 / <150 ms |
| Token restoration errors | 0 |
| Cross-tenant or cross-request leakage failures | 0 |
| Valid requests rejected by dependency failure | measured and budgeted per dependency |
| Valid Stage 4 clean-pool failures | <0.5% on the declared workload |
| Stream corruption or ambiguous disconnect | 0 |
| Memory growth after 24-hour stabilization | <5% |

Dashboards must separate policy blocks from guard-model outage, Redis outage, upstream timeout, rate-limit exhaustion, malformed response, clean-pool failure, and internal error. Track counts and rates by tenant without exposing sensitive payloads. Alert on false-block review outcomes and sustained fail-closed increases.

The Stage 5 internal `/metrics` endpoint exports `valence_stage5_review_requests_total`, `valence_stage5_review_failures_total`, `valence_stage5_candidates_total`, `valence_stage5_candidates_shortlisted_total`, `valence_stage5_candidates_human_review_total`, `valence_stage5_incomplete_pool_total`, `valence_stage5_model_schema_failure_total`, `valence_stage5_review_duration_seconds`, and `valence_stage5_human_review_rate`. Keep this internal endpoint behind the same network and authentication boundary as the verifier service.

The signed operations service exposes `/v1/operations/metrics` for payload-free review state, shadow volume, p50/p95/p99 latency, tokens, provider cost, and a configurable 20% volume-drift alert. Its response deliberately sets `production_slo_certified=false`; local and synthetic measurements cannot certify a deployed SLO.

Policy documents are immutable, tenant-scoped versions. Operators stage, activate, roll back, and audit versions through signed `/v1/policies` routes. Every transition records actor, version, action, and time. Local recovery uses `operations_recovery.py` to create online SQLite snapshots, verify per-database SHA-256 entries, reject tampering, and atomically restore verified copies. Production owners must run the same acceptance drill against the selected managed database and record observed RTO/RPO.

## Kafka service measures

Record sustained profiles/second, p95 batch completion, consumer lag, duplicate rate, DLQ rate, poison-message isolation, replay correctness, backpressure, and recovery time after Kafka, Redis, worker, and gateway restarts. A release claim must state hosts, topology, duration, payload distribution, TLS, and fault injection used.

## Cost ledger

Every shadow run should report total profiles, Stage 5 calls, input/output tokens, model/provider, cache hit rate, enrichment/OCR/verification charges, reviewer minutes, and failed-call cost. Publish cost per 1,000 profiles and projections at 10,000, 100,000, and 1,000,000 profiles. Separate deterministic Stage 4 cost from Stage 5 and show the LLM-call reduction achieved by the shortlist.
