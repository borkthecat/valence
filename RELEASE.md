# Release Process

Current release target: `v1.1.0`

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

This builds `valence-gateway:1.1.0` and `valence-pipeline:1.1.0` through `VALENCE_VERSION`.

## Tag

```bash
git tag -a v1.1.0 -m "Valence v1.1.0"
git push origin main v1.1.0
```

## Release Notes

`v1.1.0` hardens Valence for production evaluation:

- Raises deterministic pipeline scale validation from 10,000 to 100,000 profiles.
- Adds calibrated Stage 4 scoring with target-channel priority and continuous era proximity.
- Adds a synthetic oracle quality check for top-1 accuracy and top-5 recall.
- Carries final Stage 4 scores into Stage 5-ready candidate pools.
- Adds enterprise gateway controls: JWT/RBAC, per-tenant rate limiting, Prometheus metrics, and hash-chained audit logs.
- Adds RS256 JWT verification, file-backed secrets loading, and audit-chain verification tooling.
