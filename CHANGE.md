# Changes

This project keeps a change record for released source modifications.

## Unreleased

- Added protected Prometheus metrics for gateway request, security, and latency counters.
- Added HS256 JWT authentication with RBAC scope checks and tenant context.
- Added RS256 JWT verification for public-key IdP-backed deployments.
- Added per-tenant fixed-window rate limiting.
- Added a hash-chained append-only gateway audit log with verification support.
- Added a pluggable gateway secrets provider interface backed by environment variables or a local JSON secrets file.
- Added a pipeline message broker interface with an in-memory implementation for local tests.
- Added enterprise smoke coverage for JWT, rate limiting, metrics, and audit chaining.
