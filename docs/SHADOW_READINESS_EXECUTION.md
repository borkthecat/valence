# Shadow-readiness execution checklist

This is the authoritative repository completion checklist. “Externally blocked”
means code cannot substitute for the required people, data, infrastructure, or
organizational authority.

| Workstream | Status | Deliverable / acceptance | Tests / evidence | Commit | Remaining risk |
| --- | --- | --- | --- | --- | --- |
| Trusted review identity | complete | Gateway derives tenant and actor from verified authentication context, enforces route RBAC and rate limits, and signs gateway-to-review-service envelopes; review service rejects unsigned or stale direct requests | Gateway TypeScript typecheck; `test_review_service_requires_signed_gateway_identity`; existing tenant-isolation tests | pending commit | Local-mode shared-secret transport requires deployment-managed rotation and private networking |
| Advisory-to-task persistence | complete | `/review` creates an atomic, idempotent durable task only for human-review-required candidates and fails closed on unavailable persistence; digests, reason/risk/uncertainty, request and trace context are retained | `test_advisory_persists_only_review_required_tasks_idempotently` and review-operation smoke tests | pending commit | Local-mode task store must be configured and production deployment must provide managed persistence |
| Shadow operations | in progress | Durable local-mode shadow lifecycle now validates outcomes/comparisons/expiry/deletion states, preserves immutable events, and provides PII-minimized export plus unmeasured-aware report fields | `test_shadow_lifecycle`; `test_shadow_rejects_invalid_delete_and_exports_minimized` | pending commit | HTTP/RBAC service boundary, full status lifecycle, legal hold, and live advisory integration remain incomplete |
| Annotation/adjudication application | complete | Tenant-scoped calibration/active/adjudication/frozen/exported lifecycle with blind balanced dual assignment, conflict exclusions, automatic material-disagreement detection, assigned adjudication, immutable labels, versioned corrections, and canonical export artifacts | `pipeline/tests/test_annotation_study.py` (3 integration tests, warnings as errors) | pending commit | Internal UI delivery remains a separate product-interface concern; the repository lifecycle contract is complete |
| Lifecycle, retention, deletion | not started | Idempotent expiry/deletion workers and receipts | Deterministic-clock tests | — | Retention policy needs owner approval |
| Persistence/recovery | in progress | SQLite local-mode boundary, migrations, backup/restore | Restart/integrity tests | `37794bc` | PostgreSQL and deployed backups external/infrastructure work |
| Observability | not started | Bounded metrics/events for review and shadow operations | Metrics tests | — | No production telemetry |
| Shadow reporting | not started | Unmeasured-aware report and readiness command | Fixture/report tests | — | Human outcomes unavailable |
| Adapter framework | not started | JSON/CSV/reference fixture adapters with manifests | Determinism and validation tests | — | Real ATS exports/permissions external |
| Fairness/metamorphic harness | not started | Controlled invariant harness, not certification | Pair/invariant tests | — | Human/legal fairness assessment external |
| Security evaluation | intentionally deferred | Existing security suite requires separately curated corpus work | Benchmark data unavailable | — | External evaluation corpus required |
| PII evaluation | intentionally deferred | Locale/entity corpora and labels | Dataset unavailable | — | External datasets/labels required |
| Recovery and resilience | not started | Local backup/restore and failure drills | Recovery tests | — | Production RTO/RPO external |
| CI/release engineering | not started | Fast/full validation workflows and artifacts | CI configuration review | — | Hosted credentials/scanners external |
| Unified readiness | in progress | `pipeline/valence_readiness.py` emits JSON or Markdown, uses only allowed statuses, and fails its exit code when repository-required work is incomplete | `test_readiness_never_promotes_missing_evidence` | pending commit | Expand capability inventory as remaining workstreams are implemented |
| Human-labelled benchmark | externally blocked | Calibration and permissioned 200-case dataset | Independent human review | — | Human reviewers, data permissions, legal approval |
