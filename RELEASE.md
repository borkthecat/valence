# Release Procedure

## Current Release

`v1.13.5` is a cross-dataset evidence research preview. It is not an enterprise-production or autonomous-decision release.

This release adds:

- Cross-dataset PII evaluation with frozen thresholds and explicit release-gate failure.
- A review-only provenance guard cascade and zero-overlap EMSCAD fraud evaluation.
- Local Label Studio review tooling, double-blind calibration support, and an offset-safe GLiNER task exporter.
- Live-job enrichment adapters that preserve unknown external-provider results rather than inferring fraud.

See [CHANGE.md](CHANGE.md) for the complete version history and [BENCHMARKS.md](BENCHMARKS.md) for measured results and limitations.

## Preflight

Run from the repository root:

```powershell
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

Run the benchmark reproducibility check when a checked-in result artifact changes:

```powershell
python pipeline/benchmarks/build_reproducibility_manifest.py --check
```

Run the optional local smoke stack without provider credentials:

```powershell
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

## Promotion Rules

- Do not claim 95% production accuracy unless every documented per-corpus gate passes.
- Do not promote PII, ranking, fraud, or review-only guard findings without the required human-labelled and shadow evidence.
- Keep unknown external verification responses unknown; they are not fraud labels.
- Tag only a clean commit after local preflight and required CI checks pass.

## Tagging

```powershell
git tag -a v1.13.5 -m "Valence v1.13.5"
git push origin main v1.13.5
```
