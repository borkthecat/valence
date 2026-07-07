# Changes

This project keeps a change record for released source modifications.

## Unreleased

- Added protected Prometheus metrics for gateway request, security, and latency counters.
- Added HS256 JWT authentication with RBAC scope checks and tenant context.
- Added per-tenant fixed-window rate limiting.
- Added a hash-chained append-only gateway audit log.
- Added a pluggable gateway secrets provider interface backed by environment variables.
- Added a pipeline message broker interface with an in-memory implementation for local tests.
- Added enterprise smoke coverage for JWT, rate limiting, metrics, and audit chaining.
