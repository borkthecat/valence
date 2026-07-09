# Release Process

Current release target: `v1.11.2` research preview

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

Accuracy preflight for prompt-injection work:

```bash
python -m pip install -r requirements-benchmark.txt
python pipeline/benchmarks/prepare_injection_matrix.py --output .benchmark-data/injection-matrix
python pipeline/benchmarks/run_injection_matrix.py --matrix .benchmark-data/injection-matrix/matrix.json --model gateway/models/prompt-injection-guard.json --output .benchmark-data/injection-matrix/report.json --repetitions 3 --timeout-seconds 120
```

The release must not be described as 95% production-accurate unless the matrix report reaches the documented gates. The current compact bundled guard remains below that bar.

Optional local image check:

```bash
cp .env.example .env
docker compose build
```

This builds `valence-gateway:1.11.2` and `valence-pipeline:1.11.2` through `VALENCE_VERSION`.

Local no-cost smoke stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

## Tag

```bash
git tag -a v1.11.2 -m "Valence v1.11.2"
git push origin main v1.11.2
```

## Release Notes

`v1.11.2` improves the bundled compact guard without overstating accuracy:

- Ships the policy-aware multilingual compact JSON guard as the local default.
- Trains on 74,963 non-test records from 15 pinned public corpora and calibrates policy thresholds on 8,495 train-only holdout records.
- Evaluates the default model with production-equivalent `direct`, `indirect`, and `secret` policy context.
- Raises the bundled strict matrix result from 3/15 to 5/15 gates, with pooled accuracy 95.82%, precision 95.28%, recall 92.22%, F1 93.73%, and FPR 2.34%.
- Keeps the release status at research preview because ten corpora still fail one or more per-corpus gates.

`v1.11.1` hardens the guard architecture without overstating accuracy:

- Adds policy-aware guard evaluation for `direct`, `indirect`, and `secret` contexts.
- Sends user messages through `GUARD_USER_POLICY` and untrusted tool messages through the `indirect` policy.
- Rejects `SECURITY_MODE=FAIL_OPEN` under `NODE_ENV=production`.
- Adds transformer training, calibration, and evaluation scripts for the fifteen-corpus matrix.
- Records that the best local policy-aware mmBERT experiment reached 9/15 strict corpus gates, while the bundled compact JSON guard remained at 3/15.
- Keeps the release status at research preview until an independently validated guard reaches the 14/15 and 95% gates repeatedly.

`v1.11.0` makes detector limitations and startup behavior measurable:

- Runs 21,485 held-out cases from 15 revision-pinned public corpora three times with strict accuracy, precision, recall, F1, and false-positive gates.
- Records that the bundled model passes 3/15 strict corpus gates; the experimental multi-corpus candidate was rejected despite 95.52% pooled accuracy because recall and per-corpus gates remained below target.
- Adds deterministic corpus preparation, global leakage removal, label-conflict removal, Unicode candidate training, and a checked-in compact results report.
- Bounds Docker engine checks to 20 seconds, builds to 8 minutes, startup to 2 minutes, and health readiness to 90 seconds.
- Reduces the measured local pipeline image build to 11.7 seconds by keeping exhaustive scale execution in pytest/CI rather than Docker image construction.
- Clarifies that the dashboard's 5/5 result validates runtime paths, not model accuracy.

`v1.10.0` replaces the initial guard baseline with reproducible multi-corpus training and stronger release evidence:

- Trains a bounded TF-IDF linear guard on 5,735 unique WamboSec and deepset training prompts.
- Measures 99.48% accuracy (Wilson 95% CI 98.48%-99.82%) and 99.56% F1 on the untouched 577-case WamboSec test split, with zero false positives.
- Retains an independent deepset distribution-shift gate at 86.21% accuracy and 84.91% F1 rather than presenting one favorable dataset as universal accuracy.
- Pins source datasets and the emitted model by SHA-256, rejects label conflicts and train/test leakage, and enforces both F1 and accuracy in CI.
- Corrects the guard-to-shield decision contract so accepted hostile model verdicts block reliably.

`v1.9.0` adds production model integration, durable ingest semantics, and external evidence:

- Ships a SHA-256-pinned local guard that raises deepset test F1 from 3.3% to 83.8%, and connects stronger PII/guard services through bounded fail-closed HTTP clients.
- Adds Kafka idempotent production, Redis-backed completion tracking, and a DLQ.
- Adds distinct multi-image views, structured links, and SSRF-resistant live URL validation.
- Publishes measured Apache-2.0 Amazon ESCI, Gretel PII, and deepset injection baselines.
- Adds deterministic local link checks and optional external dead-link checks.

`v1.8.0` corrects enterprise relevance scoring and adds defensible ranking evaluation:

- Keeps upstream relevance and anniversary evidence as separate typed fields.
- Bounds upstream relevance and preserves it through Stage 4 and Stage 5.
- Rejects non-finite ranking inputs.
- Adds a labeled JSONL evaluator with top-1 confidence intervals, top-5 recall, MRR, NDCG@5, and enforceable release thresholds.
- States explicitly that synthetic scale testing does not establish real-world accuracy.

`v1.7.0` replaces self-referential quality claims with reproducible benchmark tooling:

- Renames the synthetic Stage 4 oracle check as internal consistency and adds random and target-channel-only baselines.
- Adds PINT-compatible injection evaluation and AI4Privacy-compatible exact-span PII evaluation.
- Adds local in-process and HTTP gateway latency benchmarks with percentile and throughput output.
- Publishes measured AI4Privacy sample results and explicitly documents weak default PII breadth and phone precision.
- Adds Developer Mode jailbreak detection plus conservative phone and IPv4 PII rules.
- Adds benchmark smoke fixtures to CI.
- Documents remaining gaps: no official full PINT score, no independently labeled ranking corpus, local-only latency, and incomplete Kafka/compliance controls.

`v1.6.0` adds rich evidence profiles for more realistic enterprise accuracy work:

- Adds entity type, title, description, attributes, numeric signals, colorway, and bounded image metadata to enterprise ingestion.
- Validates image references as HTTPS URLs with SHA-256 hashes, MIME allow-listing, and explicit size bounds.
- Scores evidence quality in the stream worker, disqualifying very thin rich profiles and carrying high-quality evidence forward.
- Extends Stage 4 and Stage 5 to preserve rich evidence while keeping legacy six-field profiles compatible.
- Sanitizes rich profile text before verifier/provider routing and passes image metadata without raw image bytes.
- Adds tests proving high-signal but thin evidence cannot beat stronger evidence-backed records.

`v1.5.2` strengthens profile quality validation:

- Adds a Stage 3 profile-quality gate for schema validity, uniqueness, anomaly coverage, elevated-age coverage, boundary classes, and deterministic fingerprinting.
- Adds 10 curated profile examples covering clean winners, near misses, unauthorized-but-perfect actors, corrupted ages, boundary ages, fractional ages, far-era drift, normalization noise, and low-signal valid profiles.
- Adds pytest coverage proving curated profiles are decision-useful and not just decorative examples.
- Updates the portfolio case-study page with profile-quality rationale, examples, full-run distribution statistics, and external data-quality references.

`v1.5.1` hardens the enterprise vault layer:

- Adds a Redis-backed gateway token vault selected by `REDIS_URL`.
- Keeps raw PII out of Redis key names with HMAC-derived forward keys.
- Converts streaming surrogate reconstitution to async vault lookups while preserving fail-closed behavior.
- Starts Redis in the default Docker stack so the no-command local launcher has the required vault service.
- Adds an explicit Redis vault smoke test.

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
- Adds a self-derived synthetic oracle regression for top-1 consistency and top-5 containment.
- Carries final Stage 4 scores into Stage 5-ready candidate pools.
- Adds local Docker Compose mock-provider testing for no-cost Stage 5 requests.
- Fixes the production gateway image audit-log directory permissions for the non-root `node` user.
- Adds enterprise gateway controls: JWT/RBAC, per-tenant rate limiting, Prometheus metrics, and hash-chained audit logs.
- Adds RS256 JWT verification, file-backed secrets loading, and audit-chain verification tooling.
