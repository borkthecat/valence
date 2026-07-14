# Project Blockers

This is the current production punch list for Valence. It separates engineering blockers from tooling or release-process issues.

## Domain Call

Valence should take candidate/job profiles as the first real domain. That matches the existing Stage 3 through Stage 5 profile pipeline and lets one evaluation stream cover ranking quality, fraud resistance, and adversarial profile text. Product matching has better public benchmarks, but it would validate a different product unless Valence is repositioned around commerce listings.

## Priority 1: Guard Model Provenance Gap

The completed V6 provenance run and selective expert routing now pass the risk-calibrated operating profile: 96.23% accuracy, 95.42% precision, 93.33% recall, 94.36% F1, and 2.29% aggregate false-positive rate on the pinned 15-corpus held-out matrix. `hse_llm` and `cgoosen_combined` remain review-only because their low-recall expert routes are not safe automatic blockers. `pipeline/remediation/shadow_review_loop.py` captures those review events with basic PII redaction and joins only explicit human decisions into retraining records.

The gateway now also has an opt-in shadow-review capture hook on the live reverse-proxy path. Set `SHADOW_REVIEW_LOG_PATH` to a JSONL destination and keep `SHADOW_REVIEW_SOURCES=hse_llm,cgoosen_combined` to collect redacted source-review events from requests that include `source_id` or `sourceId`. This is wired but disabled by default; a production or staging shadow run and reviewer decisions are still required. Benchmark records cannot substitute for either.

The compact bundled guard is not enterprise-grade and remains advisory. Set `GUARD_MODEL_ENFORCEMENT=block` only for a separately validated model after `pipeline/shadow_readiness_gate.py` passes. The v1.13.4 compact-to-V6 cascade improves pooled shadow metrics to 97.29% accuracy and 95.97% F1 at 1.75% FPR, but the test-aware routing margin is not a frozen release threshold and two secret-policy sources still fail badly.

| Suite | F1 | Primary failure |
| --- | ---: | --- |
| Direct attack | 95.23% | near gate, still corpus-sensitive |
| Indirect / provenance | 81.95% | low recall |
| Secret exfiltration | 75.76% | low precision and recall |
| Over-defense / NotInject | 61.36% accuracy | benign trigger-word false positives |

PIGuard reproduces its upstream NotInject behavior when evaluated canonically on raw prompts: 88.50% over-defense accuracy and 11.50% false positives. The same model fails when Valence prepends `[VALENCE_CONTEXT=direct]`, so the next model task is not a generic threshold search. It is provenance-aware fine-tuning or a wrapper that passes provenance as metadata instead of text.

Required next work:

1. Fine-tune or replace the compact guard representation for benign trigger-word over-defense. v1.12.0 added 60 benign trigger-word hard negatives plus training/calibration ingestion, but the compact guard stayed flat on NotInject: 61.65% accuracy and 38.35% false-positive rate.
2. Use the completed provenance-aware V6 transformer result as the frozen baseline and collect real review-only outcomes for the weak sources before further calibration. Do not retrain against held-out labels.
3. Keep block and review thresholds separate; do not collapse results into a single pooled score.

The PII engineering path is complete for repository scope: the optional CUDA GLiNER service uses the production HTTP contract, prediction caches contain offsets rather than source text, category thresholds are validated at startup, all 4,314 Gretel entities are included, and promotion fails closed. Five-fold Gretel calibration estimates 74.58% precision, 69.03% recall, and 71.70% F1. A separately sourced Nemotron-PII test check with these thresholds frozen reaches 74.78% precision, 55.91% recall, and 63.99% F1 across 8,168 spans. This confirms that person names and broad identifiers remain the limiting classes rather than a Gretel-only artifact. Both corpora are synthetic; remaining work requires independently annotated real spans, especially person names, broad identifiers, and jurisdictional locale sets.

Current implementation support:

- `pipeline/benchmarks/generate_provenance_pairs.py` creates contrastive examples where identical payload text receives different labels based on structured provenance.
- `pipeline/benchmarks/generate_guard_hard_negatives.py` creates benign trigger-word records for over-defense training experiments, and `pipeline/benchmarks/train_guard_model.py` can ingest those records as training-only and calibration-only JSONL.
- `gateway/src/core/filters/provenanceRouting.ts` maps provenance boundaries to guard policies and minimum model scores.
- The gateway applies provenance routing to user-session and retrieved tool content without prepending Valence tags to the text sent to the guard model.

## Priority 2: Real Candidate/Job Profile Evaluation

The synthetic profile generator proves deterministic behavior, not real-world accuracy. Candidate/job profiles need a public, independently labeled starting point before claiming production accuracy.

Use EMSCAD as the first external dataset because it provides 17,880 real job postings with 866 manually confirmed fraudulent records. It is binary fraud data, not ranking data, so it should become the first fraud/safety benchmark rather than the final ranking benchmark.

Required next work:

1. Run the completed DNS/HTTP/RDAP enrichment on a permissioned current job feed; EMSCAD does not contain enough live domains to measure the added signal honestly.
2. Retrain and compare the enriched precision-recall frontier against the frozen text-only EMSCAD operating point.
3. Convert the ranking audit queue into a human-labelled 200-item evaluation set, not a judge-only pseudo-label set.
4. Build a separate ranking dataset only after the fraud baseline is reproducible.

Current implementation support:

- `pipeline/benchmarks/export_emscad.py` converts EMSCAD CSV rows into Valence rich-profile JSONL with fraud labels and bounded risk scores.
- `pipeline/fraud_evaluator.py` measures binary fraud metrics and Fraud Exposure Rate before and after risk-adjusted reranking.
- `pipeline/benchmarks/train_emscad_fraud_model.py` now trains a deterministic TF-IDF logistic baseline on a local full EMSCAD CSV.
- `pipeline/benchmarks/train_emscad_transformer_fraud.py` now provides the stronger DeBERTa-style fraud-training path needed to chase 95% recall/F1 honestly.
- `pipeline/benchmarks/external_verification_features.py` now builds deterministic external-verification markers and optional live DNS/HTTP/RDAP checks for enriched job CSVs. RDAP uses the IANA bootstrap registry and a bounded SQLite provider cache without credentials.
- `pipeline/benchmarks/build_ranking_audit_queue.py` now supports a stratified human review queue: 100 ranker/judge disagreements, 50 top-ranked cases, and 50 bottom-ranked cases.
- v1.11.6 records a real held-out EMSCAD result: 98.88% accuracy and 88.24% F1. This clears the cold-start blocker, but it does not clear the 95% fraud-quality target.
- v1.11.7 records a full local DeBERTa-v3-small EMSCAD result: 98.66% accuracy and 85.80% F1. It did not improve the baseline, so the next fraud gains need better labelled features, calibration, or model strategy.
- v1.11.8 adds metadata markers and weighted transformer loss. Weighted DeBERTa improves to 87.65% F1, and metadata TF-IDF reaches 92.36% precision but only 83.82% recall. The current held-out precision-recall frontier shows at least 95% recall costs too much precision, so the 95% fraud target is blocked on stronger labels/features/modeling, not another threshold tweak.
- v1.12.0 adds EMSCAD false-negative analysis and ensemble evaluation. Its random split reached 92.99% precision, 84.39% recall, 88.48% F1, and 0.32% false-positive rate, but is retained as regression evidence only.
- v1.13.4 adds structural markers and asymmetric false-positive cost. Across 4,942 company/domain/template campaign groups with zero train/test overlap, the selected cost-32 run reaches 90.15% precision, 64.32% recall, 75.08% F1, and 0.48% FPR. This is a materially stronger precision-first triage point, but recall is too low for automatic blocking.
- The external verification pipeline is implemented and bounded: domain/email and posting-URL mismatch, DNS/HTTP liveness, persistent cache, and rate-limited provider-cache boundaries. EMSCAD itself has insufficient current company-domain and registry evidence to validate these as production fraud signals. Deploying the adapters requires a current job-feed source, approved provider credentials where applicable, and independently reviewed fraud labels.

## Priority 3: Indirect Injection Needs Schema, Not Just More Data

Indirect injection is weak because untrusted text is currently represented as prompt text plus a policy tag. Real attacks depend on source: user message, system instruction, tool output, retrieved document, profile description, source link, or image OCR text.

Required next work:

1. Carry provenance as structured fields in benchmark records.
2. Train/evaluate guards with provenance metadata preserved. The full V6 provenance run has completed and is the current frozen risk-calibrated evidence baseline; future work must compare against it on untouched and shadow-labelled splits.
3. Add fixtures where the same text is benign in a user request but hostile in tool output.
4. Measure tagged versus untagged performance to prove the schema helps.

## Priority 4: Multimodal Evidence Is Metadata-Only

Valence accepts image metadata and URLs, not raw image bytes. That is good for security and cost, but it means the current system cannot detect hidden text inside images unless OCR is added deliberately.

Required next work:

1. Decide whether images will ever be sent to an LLM or OCR model.
2. If yes, add bounded OCR extraction and treat OCR text as untrusted retrieved content.
3. If no, keep image work focused on evidence integrity: HTTPS, MIME, size, hash, duplicates, liveness, and provenance.

## Current Readiness

The repository-required release controls are complete: signed review/shadow operations, deterministic ATS adapters, metamorphic regression checks, policy rollback, local backup/restore drills, payload-free SLO/drift metrics, RDAP domain evidence, live Docker CI coverage, production-path PII evaluation, explicit guard promotion policy, group-held-out fraud evaluation, and fail-closed PII/shadow gates. Run `python pipeline/valence_readiness.py` for the machine-readable status.

Valence remains a research preview rather than an enterprise automatic-enforcement product. Human-labelled outcomes are deliberately the final evidence phase. Other remaining items are deployment facts the repository cannot manufacture: a permissioned current job feed for measured RDAP/domain evidence, managed persistence and secrets, production recovery/SLO measurements, image/OCR product scope, and legal approval. The last independent audit scores are historical pre-completion values and must not be reused as current scores.
