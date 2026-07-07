# Changes

This project keeps a change record for released source modifications.

## 1.1.0

- Raised deterministic pipeline scale validation from 10,000 to 100,000 profiles.
- Added calibrated Stage 4 scoring with target-channel priority and continuous era proximity.
- Added synthetic oracle quality validation for ranking accuracy and top-5 recall.
- Added Stage 5-ready pool export with final Stage 4 scores.

- Added protected Prometheus metrics for gateway request, security, and latency counters.
- Added HS256 JWT authentication with RBAC scope checks and tenant context.
- Added RS256 JWT verification for public-key IdP-backed deployments.
- Added per-tenant fixed-window rate limiting.
- Added a hash-chained append-only gateway audit log with verification support.
- Added a pluggable gateway secrets provider interface backed by environment variables or a local JSON secrets file.
- Added a pipeline message broker interface with an in-memory implementation for local tests.
- Added enterprise smoke coverage for JWT, rate limiting, metrics, and audit chaining.
