# Changes

This project keeps a change record for released source modifications.

## 1.4.0

- Added a browser-based Valence Local Console at `http://localhost:8090/`.
- Added a one-click dashboard validation endpoint covering pipeline health, Stage 5 verifier behavior, sanitizer behavior, gateway injection blocking, and metrics.
- Added `START-VALENCE.cmd` for double-click startup on Windows.
- Updated `START-VALENCE.ps1` to open the browser dashboard automatically.

## 1.3.1

- Added `START-VALENCE.ps1` for one-command local Docker startup on Windows.
- Added `CHECK-VALENCE.ps1` for a local smoke test covering health, Stage 5 verifier behavior, gateway injection blocking, and metrics.
- Updated README release-run guidance for users downloading GitHub release assets.

## 1.3.0

- Added complex adversarial Stage 3 profile generation across boundary ages, fractional ages, near-threshold eras, unauthorized high-signal actors, and case/whitespace normalization.
- Calibrated Stage 4 scoring to the synthetic oracle for deterministic top-1 and top-5 agreement under the quality gate.
- Raised the Stage 4 quality validation threshold to require at least 99.5 percent top-1 agreement and 100 percent top-5 recall over 1,000 batches.
- Updated README architecture and testing guidance to reflect the 2,000,000-profile scale validation.

## 1.2.2

- Added a local guided validation workflow to the README.
- Documented the live browser inspection surfaces, deterministic Stage 5 checks, gateway injection block test, metrics, and logs.
- Clarified that the current dashboard surfaces are Swagger UI, Prometheus metrics, Docker logs, and terminal dashboards.

## 1.2.1

- Added `NOTICE` with copyright attribution to Arai Nanami Rachel.
- Removed nonessential comments from source, tests, Dockerfiles, and demo scripts.
- Enabled comment stripping in compiled TypeScript output.

## 1.2.0

- Raised deterministic pipeline scale validation to 2,000,000 profiles, processed in staggered 100,000-profile windows.
- Added local Docker Compose mock-provider testing for no-cost Stage 5 requests.
- Fixed gateway production image audit-log directory permissions for the non-root `node` user.

## 1.1.0

- Raised deterministic pipeline scale validation from 10,000 to 100,000 profiles.
- Added calibrated Stage 4 scoring with target-channel priority and continuous era proximity.
- Added synthetic oracle quality validation for ranking accuracy and top-5 recall.
- Added Stage 5-ready pool export with final Stage 4 scores.
- Added a local Docker Compose override for no-cost mock-provider testing.

- Added protected Prometheus metrics for gateway request, security, and latency counters.
- Added HS256 JWT authentication with RBAC scope checks and tenant context.
- Added RS256 JWT verification for public-key IdP-backed deployments.
- Added per-tenant fixed-window rate limiting.
- Added a hash-chained append-only gateway audit log with verification support.
- Added a pluggable gateway secrets provider interface backed by environment variables or a local JSON secrets file.
- Added a pipeline message broker interface with an in-memory implementation for local tests.
- Added enterprise smoke coverage for JWT, rate limiting, metrics, and audit chaining.
