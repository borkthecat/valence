# Shadow-readiness execution checklist

This is the authoritative repository completion checklist. “Externally blocked”
means code cannot substitute for the required people, data, infrastructure, or
organizational authority.

| Workstream | Status | Deliverable / acceptance | Tests / evidence | Commit | Remaining risk |
| --- | --- | --- | --- | --- | --- |
| Trusted review identity | in progress | Gateway-derived, cryptographically verified actor and tenant context | Direct caller-forgery and tenant-isolation tests | — | Current local service is not public-safe |
| Advisory-to-task persistence | not started | Idempotent review-task creation from `/review` | End-to-end review/task test | — | Persistence failure semantics undefined |
| Shadow operations | not started | Durable shadow runs, replay, outcomes, export, report | Tenant/isolation/replay tests | — | No operational shadow evidence |
| Annotation/adjudication application | not started | Blind dual review, disagreement, freeze, canonical export | Integration/browser tests | — | Requires human calibration for validation |
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
| Unified readiness | not started | JSON/Markdown evidence report | Command test | — | Must not score missing evidence as pass |
| Human-labelled benchmark | externally blocked | Calibration and permissioned 200-case dataset | Independent human review | — | Human reviewers, data permissions, legal approval |
