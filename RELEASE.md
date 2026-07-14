# Release Process

Current release target: `v1.13.5` cross-dataset evidence research preview

## v1.13.5

- Adds an optional independently hosted transformer NER sidecar and gateway ensemble route for person-name detection. Its separate Nemotron measurement is advisory-only: 44.85% precision, 27.80% recall, and 34.33% F1 for person spans.
- Adds ignored local Apify/WhoisJSON live-job collection and a dual-review OpenAI ranking pseudo-label runner. Both outputs are explicitly release-ineligible: the live actor sample lacked domain evidence, and LLM labels are not human labels.
- Adds a local Label Studio-ready hybrid human review pack for PII and ranking. It excludes gold labels from reviewer exports, creates deterministic double-blind calibration assignments, enforces ranking Cohen's kappa >=0.80 before the pilot, and writes unresolved differences for adjudication. Human review remains required before any release claim.

- Adds a deterministic, fail-closed exporter for the CC-BY-4.0 NVIDIA Nemotron-PII test split and corrects the benchmark contract to recognize its own `GENERIC_SECRET` enforcement class.
- Runs the existing GLiNER gateway adapter against 1,000 held-out Nemotron records using thresholds frozen from Gretel calibration: 74.78% precision, 55.91% recall, and 63.99% F1 across 8,168 spans. The heuristic result is 93.57% precision, 13.72% recall, and 23.94% F1.
- Records this as synthetic cross-dataset research evidence only. It does not pass the PII gate or replace jurisdictional, human-reviewed, or production-shadow evaluation.

## v1.13.4

- Adds privacy-safe PII prediction caches, contextual entropy filters, person-name boundary alignment, and deterministic five-fold exact-span calibration. The out-of-fold Gretel result is 74.58% precision, 69.03% recall, and 71.70% F1; the release gate remains closed.
- Adds a deterministic six-locale Faker suite for regression coverage. Its 100% precision, 55.00% recall, and 70.97% F1 are synthetic diagnostics, not release evidence.
- Evaluates compact early-allow routing into frozen V6. The exploratory margin routes 40.77% of records and reaches 97.29% pooled accuracy, 96.55% precision, 95.39% recall, 95.97% F1, and 1.75% FPR, but `hse_llm` and `cgoosen_combined` still fail source gates and remain review-only.
- Adds asymmetric EMSCAD training and structural markers. On a 4,942-group holdout with zero train/test overlap, the selected cost-32 point reaches 97.26% accuracy, 90.15% precision, 64.32% recall, 75.08% F1, and 0.48% FPR.
- Adds dual-review silver-label adjudication and ranking weight-sweep tooling. The public ESCI sweep did not improve the baseline and cannot substitute for candidate/job human labels.

## v1.13.3

- Makes the bundled compact guard advisory by default; model-only blocking now requires explicit `GUARD_MODEL_ENFORCEMENT=block` promotion after shadow gates pass.
- Adds an optional authenticated, CUDA-capable GLiNER PII classifier service and benchmarks external classifiers through the same HTTP span adapter used in production.
- Corrects PII taxonomy accounting from 25.1% selected-label coverage to all 4,314 declared sensitive spans. Category calibration lifts the production-path GLiNER combination to 75.36% precision, 69.05% recall, and 72.07% F1; the machine release gate correctly remains closed.
- Adds an exact-span PII gate and a human-reviewed shadow gate with precision, recall, agreement, and latency assertions.
- Adds a zero-overlap EMSCAD company/domain/template group holdout. The best bounded regularization run reaches 97.42% accuracy, 62.56% precision, 82.47% recall, 71.15% F1, and 1.98% FPR across 3,998 test records.
- Renames stateful fraud modules to product-facing names and moves ongoing work to the non-tool-prefixed `release/v1.13.3-readiness` branch.

The older random-split EMSCAD result (88.48% F1) remains useful regression evidence but is no longer presented as the production-generalization baseline.

## v1.13.2

- Corrects Gretel IPv4 and credit-card label aliases in the exact-span PII benchmark.
- Tightens phone validation to reject numeric identifier collisions while preserving international extensions.
- Adds value-only contextual spans for API keys, passwords, and spaced SSNs.
- Improves the 1,000-record Gretel supported-label result to 92.66% precision, 71.16% recall, and 80.50% F1, while retaining the 25.08% taxonomy-coverage limitation.
- Publishes the benchmark completion and human-labelled ranking procedure in `docs/BENCHMARK_COMPLETION_PLAN.md`.

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

Risk-calibrated guard preflight:

```bash
python pipeline/remediation/assert_operating_standard.py --report gateway/benchmarks/results/v1.13.1-v6-enterprise-balanced-matrix.json --profile gateway/benchmarks/enterprise-operating-standard.json --output gateway/benchmarks/results/v1.13.1-enterprise-operating-standard.json
```

The profile requires 96% accuracy, 95% precision, 93% recall, 94% F1, 3% aggregate FPR, and 5% maximum source FPR. Sources below the configured 50% recall are review-only. Before promotion, run the review sources in shadow mode and merge explicit human decisions; do not use model predictions as labels.

Optional local image check:

```bash
cp .env.example .env
docker compose build
```

This builds `valence-gateway:1.13.5` and `valence-pipeline:1.13.5` through `VALENCE_VERSION`.

Local no-cost smoke stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --env-file .env.example up --build
```

## Tag

```bash
git tag -a v1.13.5 -m "Valence v1.13.5"
git push origin main v1.13.5
```

## Release Notes

`v1.13.1` completes repository-owned operational hardening without changing the measured model operating points:

- Adds deterministic talent adapters, identity-only metamorphic regression checks, policy rollback, integrity-checked recovery drills, SLO/drift aggregates, and credential-free RDAP domain evidence.
- Adds CI dependency and built-image inventories while keeping deployed signing and production SLO certification external.
- Leaves independently human-labelled talent and shadow outcomes as the final evidence step.

`v1.13.0` adds the versioned advisory Talent Integrity review contract while preserving the risk-calibrated provenance guard:

- Records the V6 selective expert routing matrix at 96.23% accuracy, 95.42% precision, 93.33% recall, 94.36% F1, and 2.29% aggregate FPR.
- Adds an enforce/review routing decision so `hse_llm` and `cgoosen_combined` cannot automatically block while their held-out recall remains below 50%.
- Adds a privacy-reduced shadow capture and explicit human-label merger for those review sources.
- Keeps the status at research preview pending a real shadow run and independently reviewed production labels.

`v1.11.8` tests the fraud-improvement hypothesis and records the blocker:

- Adds structural EMSCAD metadata markers to TF-IDF and transformer fraud model inputs.
- Uses explicit class-weighted cross-entropy for the transformer fraud trainer.
- Changes threshold tie-breaking to avoid precision-only bias when validation scores tie.
- Records weighted DeBERTa-v3-small at 98.83% accuracy, 89.22% precision, 86.13% recall, and 87.65% F1.
- Records metadata TF-IDF at 98.88% accuracy, 92.36% precision, 83.82% recall, and 87.88% F1.
- Keeps the release status at research preview because the current precision-recall frontier cannot reach 95% recall without reducing precision to roughly 46-54%.

`v1.11.7` turns the cold-start baselines into executable improvement loops:

- Adds a DeBERTa-style EMSCAD transformer fraud trainer with stratified splits, class-balanced sampling, threshold calibration, and optional model export.
- Records the first full DeBERTa-v3-small EMSCAD run: 98.66% accuracy, 87.88% precision, 83.82% recall, and 85.80% F1. This does not beat the TF-IDF baseline.
- Adds a high-discrepancy ranking audit queue so candidate/job human labelling targets the rows most likely to improve the ranker.
- Wires provenance-generated JSONL and special-token registration into transformer guard training, including embedding resizing before fine-tuning.
- Adds tests for provenance-token ingestion, ranking audit prioritization, and transformer EMSCAD split integrity.
- Keeps the release status at research preview because the 95% fraud, ranking, and provenance guard claims still require completed repeated runs.

`v1.11.6` closes the immediate cold-start data blockers:

- Verifies the full EMSCAD CSV locally at 17,880 records with 866 fraudulent labels and the expected text fields.
- Adds a deterministic TF-IDF logistic fraud baseline and checks in aggregate held-out metrics: 98.88% accuracy, 89.82% precision, 86.71% recall, and 88.24% F1.
- Adds a candidate/job ranking judge-task builder so LLM-assisted pseudo-labeling can produce reviewable pairwise labels instead of ad hoc manual scoring.
- Emits a special-token manifest from the provenance contrastive generator for downstream guard fine-tuning.
- Keeps the release status at research preview because the fraud F1/recall are not yet at 95%, and the ranking labels still need independent review.

`v1.11.5` adds the first production-oriented evaluation layer for provenance and job-profile fraud:

- Adds provenance-aware contrastive data generation for identical prompt-injection payloads under user, raw-source, retrieved-document, and quoted-article envelopes.
- Wires active gateway guard routing so provenance controls guard policy and minimum model score without polluting model input text with Valence tags.
- Adds EMSCAD CSV import and Fraud Exposure Rate evaluation for candidate/job profile fraud baselining.
- Keeps the release status at research preview until the full EMSCAD dataset, provenance-trained guard model, and independently labelled ranking data pass repeatable gates.

`v1.11.4` corrects the PIGuard validation path and project punch list:

- Adds `PROJECT_BLOCKERS.md` with the current production blockers and candidate/job profile domain call.
- Adds `--no-policy-prefix` to the transformer evaluator so external guard models can be benchmarked canonically.
- Records that canonical PIGuard evaluation on NotInject reaches 88.50% over-defense accuracy, while Valence provenance tags create domain shift unless the model is fine-tuned or wrapped deliberately.

`v1.11.3` corrects the benchmark framing and exposes over-defense:

- Splits prompt-injection reporting into direct attack, indirect/provenance, secret-exfiltration, and over-defense suites.
- Adds the pinned NotInject exporter for benign trigger-word-heavy prompts.
- Records that the bundled compact guard passes 5/15 strict corpus gates but has 38.64% false positives on NotInject.
- Extends the transformer evaluator so external Hugging Face guard models can be tested by ID before adoption.
- Keeps the release status at research preview because the current guard is not production-grade across indirect/provenance, secret-exfiltration, or over-defense suites.

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
