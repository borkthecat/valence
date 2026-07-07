# Release Process

Current release target: `v1.2.0`

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

This builds `valence-gateway:1.2.0` and `valence-pipeline:1.2.0` through `VALENCE_VERSION`.

Local no-cost smoke stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

## Tag

```bash
git tag -a v1.2.0 -m "Valence v1.2.0"
git push origin main v1.2.0
```

## Release Notes

`v1.2.0` hardens Valence for production evaluation and local testing:

- Raises deterministic pipeline scale validation from 10,000 to 2,000,000 profiles, processed in staggered 100,000-profile windows.
- Adds calibrated Stage 4 scoring with target-channel priority and continuous era proximity.
- Adds a synthetic oracle quality check for top-1 accuracy and top-5 recall.
- Carries final Stage 4 scores into Stage 5-ready candidate pools.
- Adds local Docker Compose mock-provider testing for no-cost Stage 5 requests.
- Fixes the production gateway image audit-log directory permissions for the non-root `node` user.
- Adds enterprise gateway controls: JWT/RBAC, per-tenant rate limiting, Prometheus metrics, and hash-chained audit logs.
- Adds RS256 JWT verification, file-backed secrets loading, and audit-chain verification tooling.
