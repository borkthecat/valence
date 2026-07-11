# Changes

This project keeps a change record for released source modifications.

## 1.12.0

- Added risk-calibrated provenance guard validation using the final V6 selective-routing benchmark artifact: 96.23% accuracy, 95.42% precision, 93.33% recall, 94.36% F1, and 2.29% aggregate false-positive rate.
- Added an operating-standard assertion script so the release gate checks aggregate accuracy, precision, recall, F1, aggregate false-positive rate, and maximum per-source false-positive rate from structured benchmark reports.
- Added enforce/review routing decisions for source-specific guard behavior so `hse_llm` and `cgoosen_combined` remain review-only while their held-out recall is below 50%.
- Added privacy-reduced shadow review tooling to capture real events, deduplicate them, redact common PII, and merge only explicit human labels.
- Added EMSCAD external verification feature plumbing, including email/domain mismatch checks, posting URL mismatch checks, liveness probes, and provider-cache boundaries for future WHOIS, registry, and reputation adapters.
- Kept the release status at research preview because the review-only guard sources still need a real shadow run and EMSCAD still needs live external verification signals before production fraud-detection claims are justified.

## 1.11.8

- Added EMSCAD structural metadata markers to the TF-IDF and transformer fraud text streams, including logo, screener-question, remote-work, salary, and department signals.
- Replaced the transformer trainer's default classification loss with explicit class-weighted cross-entropy using the training split's legitimate-to-fraud ratio.
- Changed validation-threshold tie-breaking to prefer the lower threshold when scores are equal, avoiding accidental precision-only bias.
- Ran the full weighted DeBERTa-v3-small EMSCAD experiment: 98.83% accuracy, 89.22% precision, 86.13% recall, 87.65% F1, and 0.53% false-positive rate.
- Ran the metadata TF-IDF EMSCAD experiment: 98.88% accuracy, 92.36% precision, 83.82% recall, 87.88% F1, and 0.35% false-positive rate.
- Confirmed the current precision-recall frontier does not support a 95% fraud claim: forcing at least 95% recall drops best observed precision to roughly 46-54% on the held-out split.

## 1.11.7

- Added a transformer EMSCAD fraud-training path for DeBERTa-style sequence classifiers with stratified train/validation/test splits, threshold calibration, class-balanced sampling, and optional model artifact export.
- Ran the full local DeBERTa-v3-small EMSCAD experiment and recorded the aggregate result: 98.66% accuracy, 87.88% precision, 83.82% recall, 85.80% F1, and 0.59% false-positive rate.
- Added a high-discrepancy ranking audit queue so human labelling can focus on candidate/job pairs where the ranker and judge disagree most.
- Extended transformer guard training to consume provenance-generated JSONL and register provenance special tokens before resizing model embeddings.
- Added pytest coverage for provenance-token ingestion, ranking audit prioritization, and transformer EMSCAD split integrity.
- Kept the accuracy claim unchanged: the DeBERTa run did not beat the v1.11.6 TF-IDF fraud baseline, so Valence still has no 95% EMSCAD fraud claim.

## 1.11.6

- Downloaded and verified a full public EMSCAD CSV locally: 17,880 records, 866 fraudulent, 17,014 legitimate, and the expected text/risk columns.
- Added a deterministic EMSCAD TF-IDF logistic fraud baseline with train/validation/test split, validation-threshold calibration, held-out fraud metrics, and Fraud Exposure Rate reporting.
- Recorded the full EMSCAD trained baseline result: 98.88% accuracy, 89.82% precision, 86.71% recall, 88.24% F1, 0.50% false-positive rate, and top-50 model-adjusted FER reduced from 4.00% to 0.00%.
- Added LLM-judge task generation for candidate/job ranking pseudo-label bootstrapping.
- Extended provenance-pair generation with a special-token manifest for downstream guard fine-tuning.

## 1.11.5

- Added provenance-aware contrastive prompt-injection data generation so the same payload can be evaluated as direct user text, untrusted retrieved/source text, or quoted article evidence.
- Added active provenance routing in the gateway guard path, including conservative direct thresholds and stricter indirect routing for retrieved tool content without prepending provenance tokens to model text.
- Added an EMSCAD fake-job importer and fraud evaluator that report precision, recall, F1, false-positive rate, and Fraud Exposure Rate before and after risk-adjusted reranking.
- Added Python and gateway smoke coverage for provenance routing, EMSCAD mapping, and fraud exposure reduction on the checked-in fixture.
- Documented that this is a measurable evaluation layer, not a final 95% production-accuracy claim until the full public EMSCAD CSV and independently labelled ranking data are run.

## 1.11.4

- Added `PROJECT_BLOCKERS.md` with the current production punch list and candidate/job profile domain call.
- Added `--no-policy-prefix` to the transformer guard evaluator so external Hugging Face guard models can be tested canonically without Valence provenance text.
- Reproduced PIGuard's canonical NotInject behavior locally: 300 true negatives, 39 false positives, 88.50% over-defense accuracy, and 11.50% false-positive rate.
- Documented that PIGuard is viable as a base model, but Valence provenance tags create domain shift unless the model is fine-tuned or wrapped deliberately.

## 1.11.3

- Split prompt-injection evaluation into explicit suites for direct attacks, indirect/provenance attacks, secret exfiltration, and over-defense instead of treating a pooled score as a single accuracy claim.
- Added suite rollups to both the local JSON guard matrix runner and transformer guard evaluator.
- Added a pinned NotInject exporter for benign trigger-word-heavy over-defense evaluation.
- Validated that the bundled compact guard still passes 5/15 strict corpus gates, with direct attacks at 95.23% F1, indirect/provenance at 81.95% F1, and secret-exfiltration at 75.76% F1.
- Measured the bundled guard on NotInject: 208 true negatives and 131 false positives, a 38.64% benign false-positive rate. This confirms the trigger-word over-defense gap remains open.
- Extended the transformer evaluator so Hugging Face guard models can be benchmarked by model ID with explicit `--trust-remote-code`, plus `--no-policy-prefix` for canonical external-model evaluations.
- Added `PROJECT_BLOCKERS.md` to track the production blockers, candidate/job profile domain call, and next evaluation work.

## 1.11.2

- Replaced the default prompt-injection guard with a policy-aware multilingual compact model trained on 74,963 non-test records from 15 pinned public corpora and calibrated on 8,495 train-only holdout records.
- Updated the gateway local model loader to support policy-aware compact artifacts and per-policy thresholds while preserving strict schema validation and SHA-256 pinning.
- Updated the injection benchmark fixtures and runner so matrix cases are evaluated with the same `direct`, `indirect`, and `secret` context production requests use.
- Raised the bundled compact guard from 3/15 to 5/15 strict corpus gates. This is an improvement, not a 95% enterprise accuracy claim; the release remains a research preview.

## 1.11.1

- Added policy-aware prompt-injection guard context so direct user prompts, untrusted tool output, and secret-exfiltration checks can use separate thresholds and model behavior.
- Routed gateway user messages through `GUARD_USER_POLICY` and tool messages through the stricter `indirect` policy, with smoke coverage proving the HTTP guard receives the policy value.
- Refused `SECURITY_MODE=FAIL_OPEN` when `NODE_ENV=production`, keeping scanner or model failures from silently forwarding production traffic.
- Added transformer guard training, calibration, and evaluation tooling for the fifteen-corpus matrix. The best local policy-aware mmBERT experiment passed 9/15 strict gates; later augmentation attempts and public off-the-shelf classifiers did not improve it enough to justify a 95% enterprise claim.
- Documented that the checked-in compact JSON guard still passed 3/15 strict gates in 1.11.1, while the 9/15 transformer result was an experimental local artifact and not the bundled default.
- Added train-only synthetic direct and indirect examples for future experiments, including corrected multilingual prompt variants.
- Split heavyweight transformer dependencies into `requirements-transformer.txt` so the normal benchmark workflow stays lightweight.

## 1.11.0

- Added a revision-pinned fifteen-corpus prompt-injection matrix with 21,485 held-out cases, global train/test overlap removal, conflict removal, deterministic splits, and three-run stability checks.
- Added strict per-corpus gates requiring at least 95% accuracy, precision, recall, and F1 with at most 5% false-positive rate; the bundled model currently passes 3 of 15 and is explicitly not presented as broadly production-accurate.
- Added multilingual candidate training with Unicode features, per-source/class caps, and rejection of candidates that regress existing gates.
- Preserved English-model tokenization while isolating Unicode tokenization to multilingual model artifacts.
- Added Docker engine, build, startup, benchmark, and health deadlines with diagnostic logs and truthful failure handling.
- Added a manual GitHub matrix workflow that preserves the evaluation report and fails when any strict corpus gate is missed.
- Replaced the full Stage 3 execution during image construction with compile/import checks, reducing the measured pipeline build from about 57 seconds of executable work to 11.7 seconds end to end locally.
- Renamed dashboard checks as runtime validation so 5/5 health checks cannot be mistaken for accuracy evidence.

## 1.10.0

- Replaced the raw-count guard with a SHA-256-pinned word/character TF-IDF linear model trained on 5,735 deduplicated WamboSec and deepset training prompts.
- Added a 577-case MIT-licensed WamboSec release gate: 99.48% accuracy, 99.13% recall, 99.56% F1, and zero false positives on its untouched test split.
- Retained the separate 116-case deepset gate, reporting 86.21% accuracy and 84.91% F1 to expose cross-dataset distribution sensitivity.
- Fixed guard integration so a hostile verdict that clears the configured model-score threshold is authoritative instead of being weakened by applying the outer shield threshold a second time.
- Added checksum-verified bounded dataset downloads, normalized deduplication, conflicting-label rejection, train/test leakage detection, fixture attribution, and separate F1 and Wilson accuracy lower-bound CI thresholds.

## 1.9.0

- Added a SHA-256-pinned local guard model that raises independent deepset test F1 from 3.3% to 83.8%, plus secure HTTP clients for stronger trained PII and guard services.
- Added Kafka idempotent production, deterministic batch/message identities, Redis staging and completion tracking, duplicate suppression, and a dead-letter topic.
- Added multi-view image evidence, structured source links, digest-based duplicate suppression, and optional SSRF-resistant live URL/MIME validation.
- Added Apache-2.0 dataset exporters and measured baselines for Amazon ESCI ranking, Gretel PII spans, and deepset prompt injections.
- Added local and external link validation and documented non-commercial datasets excluded from enterprise defaults.

## 1.8.0

- Corrected enterprise ingestion so relevance no longer masquerades as anniversary evidence.
- Preserved a bounded 0-to-1 source-relevance score through Stage 4 and Stage 5.
- Rejected non-finite ranking values and bounded gateway `raw_score` input to 0 through 100.
- Added independently labeled ranking evaluation with top-1 Wilson confidence intervals, top-5 winner recall, MRR, NDCG@5, fail-closed counts, and enforceable release thresholds.
- Documented why millions of synthetic profiles validate robustness but cannot establish real-world accuracy.

## 1.7.0

- Reframed the Stage 4 synthetic oracle as an internal consistency regression rather than external accuracy evidence.
- Added random and target-channel-only ranking baselines for synthetic task-difficulty context.
- Added PINT-compatible prompt-injection benchmarking with precision, recall, F1, false-positive rate, and category errors.
- Added AI4Privacy-compatible exact-span PII benchmarking with compatible-label coverage and per-label metrics.
- Added in-process security-path and full local HTTP gateway latency benchmarks with p50, p95, p99, throughput, and direct-upstream comparison.
- Added conservative phone and IPv4 heuristic PII rules and explicit Developer Mode jailbreak detection.
- Added `BENCHMARKS.md` with measured external/sample results, reproduction commands, limitations, and unmeasured production areas.
- Added benchmark smoke fixtures to CI and corrected README claims about detected PII, prompt-injection limits, synthetic distributions, and ranking accuracy.

## 1.6.0

- Added rich enterprise profile evidence fields for ingestion: entity type, title, description, attributes, numeric signals, colorway, and bounded image metadata.
- Added HTTPS-only image evidence validation with SHA-256 hashes, MIME allow-listing, size bounds, and strict payload parsing at the gateway boundary.
- Added evidence-quality scoring in the stream worker so rich profiles can be penalized or disqualified when their real-world evidence is too thin.
- Extended Stage 4 to carry rich evidence into Stage 5 while preserving legacy six-field profile behavior.
- Extended Stage 5 schemas and sanitization so rich text evidence is neutralized before verifier/provider routing and image metadata is passed without raw image bytes.
- Added tests proving thin high-signal profiles cannot win over stronger evidence-backed records.

## 1.5.2

- Added a Stage 3 profile-quality gate covering schema validity, uniqueness, anomaly coverage, elevated-age coverage, boundary classes, and deterministic fingerprinting.
- Added 10 curated profile examples that exercise clean winners, authorized near misses, unauthorized-but-perfect actors, corrupted ages, boundary ages, fractional ages, far-era drift, normalization noise, and low-signal valid candidates.
- Added pytest coverage proving the curated examples are decision-useful: Stage 4 must disqualify the corrupt profiles and still form a valid pool from eligible candidates.
- Updated the portfolio case-study page with profile-quality rationale, examples, measured full-run distribution statistics, and external data-quality references.

## 1.5.1

- Added a Redis-backed gateway token vault selected by `REDIS_URL`, with HMAC-derived forward keys so raw PII does not appear in Redis key names.
- Converted PII tokenization and streaming surrogate reconstitution to async vault lookups while preserving fail-closed behavior for expired or out-of-scope surrogates.
- Started Redis in the default Docker stack so the double-click local launcher has the same vault dependency it advertises.
- Added an explicit Redis vault smoke test for distributed round trips, restoration, revocation, and key-name hygiene.

## 1.5.0

- Added enterprise Kafka/Redis Compose topology behind the `enterprise` profile.
- Added authenticated `POST /api/v1/ingest` with strict Zod payload validation.
- Added JWKS-backed RS256 enterprise ingestion auth, with explicit local gateway-key mode for no-IdP demos.
- Added Kafka producer support in the gateway and a Python `stream_worker.py` Kafka consumer that maps enterprise records into Stage 4 batches.
- Updated `run_system_demo.sh` to create the Kafka topic and post a sample enterprise ingest batch.

## 1.4.1

- Refined the Valence Local Console with a more professional dashboard layout and system UI font stack.
- Added concise dashboard copy explaining what the local validation is for.
- Added browser-based Docker setup help when Docker Desktop is missing or not running.

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
- Added a self-derived synthetic oracle regression for ranking consistency and top-5 containment.
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
