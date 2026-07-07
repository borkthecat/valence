# Release Process

Current release target: `v1.5.0`

## Preflight

Run these from the repository root before tagging:

```bash
cd gateway
npm ci
npm run typecheck
npm run build
npm test

cd ../pipeline
python -m pip install -r requirements-dev.txt
python -W error -m pytest -q

cd ..
docker compose --env-file .env.example config
```

Optional local image check:

```bash
cp .env.example .env
docker compose build
```

This builds `valence-gateway:1.5.0` and `valence-pipeline:1.5.0` through `VALENCE_VERSION`.

Local no-cost smoke stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

## Tag

```bash
git tag -a v1.5.0 -m "Valence v1.5.0"
git push origin main v1.5.0
```

## Release Notes

`v1.5.0` adds enterprise streaming ingestion:

- Adds Kafka and Redis services behind the Compose `enterprise` profile.
- Adds authenticated `POST /api/v1/ingest` with strict Zod payload validation.
- Adds JWKS-backed RS256 enterprise ingestion auth, with explicit local gateway-key mode for no-IdP demos.
- Adds gateway Kafka producer support and a Python Kafka stream worker.
- Updates `run_system_demo.sh` to create the Kafka topic and post a sample enterprise ingest batch.

`v1.4.1` polishes the local console and setup experience:

- Refines the Valence Local Console with a more professional dashboard layout and system UI font stack.
- Adds concise dashboard copy explaining what the local validation is for.
- Opens a browser setup help page when Docker Desktop is missing or not running.

`v1.4.0` adds a no-command browser validation flow:

- Adds a browser-based Valence Local Console at `http://localhost:8090/`.
- Adds a one-click dashboard validation endpoint covering pipeline health, Stage 5 verifier behavior, sanitizer behavior, gateway injection blocking, and metrics.
- Adds `START-VALENCE.cmd` for double-click startup on Windows.
- Updates `START-VALENCE.ps1` to open the browser dashboard automatically.

`v1.3.1` adds release-ready local startup and smoke-test scripts:

- Adds `START-VALENCE.ps1` for one-command Docker startup on Windows.
- Adds `CHECK-VALENCE.ps1` to validate health, Stage 5 verifier behavior, gateway injection blocking, and metrics.
- Keeps the `v1.3.0` accuracy calibration unchanged.

`v1.3.0` improves scale-test realism and Stage 4 ranking calibration:

- Adds complex adversarial Stage 3 profile generation across boundary ages, fractional ages, near-threshold eras, unauthorized high-signal actors, and case/whitespace normalization.
- Calibrates Stage 4 scoring to the synthetic oracle, producing deterministic top-1 and top-5 agreement under the quality gate.
- Tightens Stage 4 quality validation to at least 99.5 percent top-1 agreement and 100 percent top-5 recall over 1,000 batches.
- Updates README architecture and testing guidance to show the 2,000,000-profile validation path.

`v1.2.2` is a documentation patch release:

- Adds a local guided validation workflow to the README.
- Documents the browser-visible Swagger UI, gateway metrics, live logs, known-good Stage 5 request, sanitizer check, and direct gateway block test.

`v1.2.1` is a source cleanup and attribution patch release:

- Adds Apache-style `NOTICE` attribution for Arai Nanami Rachel.
- Removes nonessential comments from source, tests, Dockerfiles, and demo scripts.
- Enables comment stripping in compiled TypeScript output.

`v1.2.0` hardens Valence for production evaluation and local testing:

- Raises deterministic pipeline scale validation from 10,000 to 2,000,000 profiles, processed in staggered 100,000-profile windows.
- Adds calibrated Stage 4 scoring with target-channel priority and continuous era proximity.
- Adds a synthetic oracle quality check for top-1 accuracy and top-5 recall.
- Carries final Stage 4 scores into Stage 5-ready candidate pools.
- Adds local Docker Compose mock-provider testing for no-cost Stage 5 requests.
- Fixes the production gateway image audit-log directory permissions for the non-root `node` user.
- Adds enterprise gateway controls: JWT/RBAC, per-tenant rate limiting, Prometheus metrics, and hash-chained audit logs.
- Adds RS256 JWT verification, file-backed secrets loading, and audit-chain verification tooling.
