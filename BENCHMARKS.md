# Benchmark Report

Measured on July 9, 2026. These results separate internal regression checks from external or independently sourced evaluation data.

## What the numbers mean

- The Stage 4 synthetic oracle is an internal consistency regression test. It is derived from the same scoring specification as the reranker and does not establish real-world ranking accuracy.
- Stage 3 anomaly percentages describe the configured synthetic generator distribution. They are test coverage inputs, not estimates of production data.
- Public benchmark results apply only to the named dataset sample, detector configuration, and machine/run described below.

## PII detection

Dataset: first 1,000 rows of Gretel.ai's Apache-2.0 [`gretel-pii-masking-en-v1`](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1) corpus.

Detector: `HeuristicPiiDetector`, without an external classifier.

| Metric | Result |
| --- | ---: |
| Annotated entities | 4,314 |
| Entities in compatible label families | 783 |
| Compatible-label coverage | 18.2% |
| Exact-span precision | 49.2% |
| Exact-span recall | 63.2% |
| Exact-span F1 | 55.3% |

Per compatible label:

| Label | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| Email | 98.3% | 99.6% | 98.9% |
| SSN | 97.3% | 59.3% | 73.7% |
| Phone | 15.1% | 29.8% | 20.1% |

This result is not production-grade. The largest gaps are label breadth and phone precision. Production deployments should connect a trained classifier through `PII_CLASSIFIER_URL`, calibrate it by locale and jurisdiction, and rerun the benchmark. The previously documented AI4Privacy sample is no longer the default because its current license restricts commercial use.

Reproduce:

```bash
python pipeline/benchmarks/export_gretel_pii.py --rows 1000 --output .benchmark-data/gretel-pii-1000.jsonl
npm --prefix gateway run benchmark:pii -- ../.benchmark-data/gretel-pii-1000.jsonl
```

## Prompt injection

The runner accepts the YAML format used by [Lakera's PINT repository](https://github.com/lakeraai/pint-benchmark):

```bash
cd gateway
npm run benchmark:injection -- /path/to/pint-compatible.yaml
```

The public eight-case `example-dataset.yaml` from the PINT repository produced 8/8 correct classifications. The v1.10.0 bundled guard is a bounded English word/character TF-IDF linear classifier trained on 5,735 unique prompts from the WamboSec and deepset training splits. All four source Parquet files are SHA-256 pinned, normalized duplicates are removed, and training aborts if either reserved test split overlaps training.

| Held-out split | Cases | Accuracy | Accuracy 95% CI | Precision | Recall | F1 | FPR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| WamboSec test | 577 | 99.48% | 98.48%-99.82% | 100.00% | 99.13% | 99.56% | 0.00% |
| deepset test | 116 | 86.21% | 78.76%-91.33% | 97.83% | 75.00% | 84.91% | 1.79% |

The WamboSec confusion matrix is 343 true positives, 231 true negatives, zero false positives, and three false negatives. The misses are Morse/Braille-only attacks. The separate deepset result is materially weaker and is published to make distribution sensitivity visible. The claim "over 95% accurate" applies only to the named 577-case English synthetic WamboSec split, not all prompt injection or production traffic.

### Fifteen-corpus matrix

v1.11.3 uses 15 revision-pinned corpora and 21,485 test records. A corpus passes only when accuracy, precision, recall, and F1 are each at least 95% and false-positive rate is no more than 5%. Results are also grouped into suites because direct prompt attacks, indirect/provenance attacks, and secret-exfiltration attacks are not the same benchmark problem.

| Corpus | Cases | Accuracy | Precision | Recall | F1 | FPR | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| WamboSec | 577 | 99.13% | 100.00% | 98.55% | 99.27% | 0.00% | Pass |
| deepset | 116 | 79.31% | 100.00% | 60.00% | 75.00% | 0.00% | Fail |
| Shomi28 | 128 | 100.00% | 100.00% | 100.00% | 100.00% | 0.00% | Pass |
| jackhhao | 262 | 94.27% | 94.29% | 94.96% | 94.62% | 6.50% | Fail |
| cgoosen guard | 4,691 | 98.98% | 91.20% | 89.76% | 90.48% | 0.50% | Fail |
| Neuralchemy | 942 | 95.22% | 96.51% | 95.29% | 95.90% | 4.87% | Pass |
| WamboSec subtle | 94 | 98.94% | 100.00% | 98.57% | 99.28% | 0.00% | Pass |
| jcanode | 5,425 | 97.51% | 89.40% | 99.16% | 94.03% | 2.89% | Fail |
| rikka multilingual | 1,276 | 84.33% | 98.73% | 70.61% | 82.33% | 0.97% | Fail |
| beratcmn Turkish | 115 | 86.09% | 100.00% | 72.88% | 84.31% | 0.00% | Fail |
| S-Labs | 2,101 | 95.53% | 99.08% | 91.91% | 95.36% | 0.86% | Fail |
| cgoosen combined | 98 | 63.27% | 91.94% | 64.77% | 76.00% | 50.00% | Fail |
| Smooth-3 | 5,500 | 95.16% | 95.47% | 94.99% | 95.23% | 4.65% | Fail |
| darkknight25 | 100 | 99.00% | 98.04% | 100.00% | 99.01% | 2.00% | Pass |
| HSE LLM | 60 | 80.00% | 64.29% | 90.00% | 75.00% | 25.00% | Fail |

The bundled model passes 5/15 strict gates. Pooled accuracy is 95.82%, precision is 95.28%, recall is 92.22%, F1 is 93.73%, and FPR is 2.34%; these pooled values are descriptive only and cannot override failed corpora. The improvement comes from replacing the old WamboSec/deepset-only English artifact with a 15-corpus multilingual compact model trained on 74,963 records and calibrated on 8,495 train-only holdout records.

Suite rollup from the checked-in v1.11.3 report:

| Suite | Corpora | Passed | Accuracy | Precision | Recall | F1 | FPR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct attack | 10 | 5 | 96.92% | 95.14% | 95.32% | 95.23% | 2.32% |
| Indirect / provenance | 3 | 0 | 84.07% | 98.91% | 69.96% | 81.95% | 0.82% |
| Secret exfiltration | 2 | 0 | 69.62% | 83.33% | 69.44% | 75.76% | 30.00% |

This changes the diagnosis. The direct-attack suite is near the strict target, while indirect/provenance and secret-exfiltration are not. More generic direct-attack examples are therefore unlikely to fix the whole system.

### Over-defense

### Risk-calibrated provenance guard

The full V6 provenance model is evaluated with selective source experts only where they improve held-out false-positive behavior. The v1.13.2 enterprise-balanced matrix passes a declared operating profile: 96.23% accuracy, 95.42% precision, 93.33% recall, 94.36% F1, 2.29% aggregate FPR, and 4.62% maximum per-source FPR. The profile is checked by `pipeline/remediation/assert_operating_standard.py` against `gateway/benchmarks/enterprise-operating-standard.json`.

`cgoosen_combined` and `hse_llm` meet the low-FPR constraint but have 14.77% and 25.00% recall respectively, so they are review-only, not automatic block routes. `pipeline/remediation/shadow_review_loop.py` creates a PII-reduced queue from real shadow events and merges explicit human labels for the next expert-data audit. These two sources are not evidence for production detection coverage until that shadow evaluation completes.

Valence now includes a pinned exporter for [NotInject](https://huggingface.co/datasets/leolee99/NotInject), a benign trigger-word-heavy benchmark introduced by the InjecGuard/PIGuard work. NotInject measures whether a guard blocks harmless prompts merely because they contain words such as "ignore" or other injection-like triggers.

On the pinned 339-case NotInject export, the bundled compact guard produced 208 true negatives and 131 false positives: 61.36% accuracy and 38.64% benign false-positive rate. Heuristic-only detection produced zero false positives on the same set, so the over-defense issue is in the compact model, not the regex layer. The checked-in artifact is `gateway/benchmarks/results/v1.11.3-notinject.json`.

A scalar confidence threshold is not a correct fix. Raising the model minimum score to 0.75 reduces NotInject false positives to 1.77%, but drops matrix recall from 92.22% to 53.08%. At 0.84, NotInject false positives reach 0%, but matrix recall drops to 30.42%. The real fix is over-defense-aware training/calibration or a stronger validated guard model.

The transformer evaluator can benchmark external guard models directly. A canonical local run of `leolee99/PIGuard` with `--trust-remote-code --no-policy-prefix --max-length 2048` reproduced the upstream NotInject result: 300 true negatives, 39 false positives, 88.50% over-defense accuracy, and 11.50% false-positive rate. The checked-in artifact is `gateway/benchmarks/results/v1.11.3-piguard-notinject-no-prefix.json`. The earlier failed cold run was caused by evaluating PIGuard on Valence-prefixed text such as `[VALENCE_CONTEXT=direct] ...`; with that prefix present, false positives rose to 261 of 339. The engineering conclusion is that PIGuard is viable as a base model, but it must be fine-tuned or wrapped deliberately for Valence provenance tags instead of adopted as a raw drop-in classifier.

A local policy-aware transformer experiment using `jhu-clsp/mmBERT-base`, train-only validation calibration, and separate `direct`, `indirect`, and `secret` policy thresholds reached 9/15 strict gates. That is useful evidence that policy separation improves the architecture, but it is not enough to claim production-grade 95% coverage. Additional train-only synthetic augmentation and two public off-the-shelf prompt-injection classifiers did not beat the 9/15 result on this matrix, so the release remains a research preview until a stronger independently validated guard reaches the target.

The corpora do not share one perfect definition of injection. Some label roleplay as malicious while others deliberately include roleplay as benign, several are synthetic or translated derivatives, and small sets have wide confidence intervals. Valence records those disagreements instead of tuning per-dataset rules against observed test labels.

Valence ships the 4.97 MB JSON guard as the local default and also supports bounded local and HTTP `GuardModelClient` integrations for independently trained enterprise models. HTTP guard services receive the normalized text and a policy value of `direct`, `indirect`, or `secret`. The compact artifact is pinned by SHA-256. Lakera's complete 4,314-input PINT corpus includes proprietary data and is not publicly downloadable, so Valence does not claim a full PINT score.

### Provenance contrastive pairs

`pipeline/benchmarks/generate_provenance_pairs.py` creates a provenance-aware contrastive set from any attack JSONL file. The same payload is wrapped as literal user text, raw web source text, retrieved document text, and quoted article evidence. Raw and retrieved source envelopes are labelled as indirect attacks; literal user tests and quoted evidence are labelled benign. This is designed to measure the exact failure mode that appeared when PIGuard was evaluated on Valence-prefixed text.

The gateway now routes provenance as structured evaluation context instead of prepending it to the text sent to the guard model. User-session content uses conservative direct routing; retrieved tool content uses indirect routing with a lower minimum hostile-model score.

```bash
python -m pip install -r requirements-benchmark.txt
python pipeline/benchmarks/prepare_injection_matrix.py --output .benchmark-data/injection-matrix
python pipeline/benchmarks/run_injection_matrix.py --matrix .benchmark-data/injection-matrix/matrix.json --model gateway/models/prompt-injection-guard.json --output .benchmark-data/injection-matrix/report.json --repetitions 3 --timeout-seconds 120
python pipeline/benchmarks/export_notinject.py --output .benchmark-data/notinject.jsonl --matrix-output .benchmark-data/notinject-matrix.json
npm --prefix gateway run benchmark:injection -- ../.benchmark-data/notinject.jsonl models/prompt-injection-guard.json
python pipeline/benchmarks/train_guard_model.py --output .benchmark-data/candidate-guard.json
python -m pip install -r requirements-transformer.txt
python pipeline/benchmarks/train_transformer_guard.py --output .benchmark-data/mmbert-policy-guard
python pipeline/benchmarks/calibrate_transformer_guard.py --model .benchmark-data/mmbert-policy-guard
python pipeline/benchmarks/evaluate_transformer_guard.py --matrix .benchmark-data/injection-matrix/matrix.json --model .benchmark-data/mmbert-policy-guard --output .benchmark-data/injection-matrix/mmbert-policy-report.json
python pipeline/benchmarks/evaluate_transformer_guard.py --matrix .benchmark-data/notinject-matrix.json --model leolee99/PIGuard --output .benchmark-data/pigguard-notinject-report.json --trust-remote-code --no-policy-prefix --max-length 2048
python pipeline/benchmarks/generate_provenance_pairs.py --input gateway/benchmarks/fixtures/wambosec-test.jsonl --output .benchmark-data/provenance-pairs.jsonl --matrix-output .benchmark-data/provenance-pairs-matrix.json --special-tokens-output .benchmark-data/provenance-special-tokens.json --limit 100
python pipeline/benchmarks/train_transformer_guard.py --output .benchmark-data/mmbert-provenance-guard --provenance-jsonl .benchmark-data/provenance-pairs.jsonl --special-tokens .benchmark-data/provenance-special-tokens.json
npm --prefix gateway run benchmark:injection -- benchmarks/fixtures/wambosec-test.jsonl models/prompt-injection-guard.json 0.95 0.95
npm --prefix gateway run benchmark:injection -- benchmarks/fixtures/deepset-test.jsonl models/prompt-injection-guard.json 0.84 0.78
```

## Ranking diagnostics

Dataset: 1,000 deterministic synthetic batches generated by Stage 3.

Ground truth: the self-derived Stage 4 scoring specification. These numbers measure implementation consistency and synthetic task difficulty, not real-world preference accuracy.

| Method | Top-1 | Top-5 |
| --- | ---: | ---: |
| Random baseline | 2.3% | 11.1% |
| Target-channel-only baseline | 7.4% | 43.7% |
| Stage 4 internal consistency | 100.0% | 100.0% |

External domain accuracy remains unmeasured until a use case supplies independently labeled profiles.

An initial external run used the first 1,000 held-out test rows from Amazon Science's Apache-2.0 ESCI corpus, grouped into 34 queries. The deterministic lexical adapter did not consume ESCI labels during scoring.

| Metric | Result |
| --- | ---: |
| Top-1 | 38.2% |
| Top-1 95% CI | 23.9%-55.0% |
| Top-5 winner recall | 94.1% |
| MRR | 0.620 |
| NDCG@5 | 0.562 |

For external evaluation, `pipeline/ranking_evaluator.py` accepts independently labeled JSONL and reports top-1 accuracy with a Wilson 95% confidence interval, top-5 winner recall, mean reciprocal rank, NDCG@5, and fail-closed batches. Release gates compare `--min-top1` against the confidence interval's lower bound rather than the point estimate. The checked-in fixture verifies metric behavior only and is not an external benchmark.

### Job-profile fraud baseline

EMSCAD is the first candidate/job profile safety benchmark because it contains real job postings with binary fraudulent labels. `pipeline/benchmarks/export_emscad.py` converts the CSV into Valence rich-profile JSONL, and `pipeline/fraud_evaluator.py` reports fraud precision, recall, F1, false-positive rate, and Fraud Exposure Rate at top-k before and after risk-adjusted reranking.

The repository includes a four-row EMSCAD-shaped smoke fixture to test the mapping and metrics. It does not include the full public dataset, so the fixture result is not an accuracy claim.

For v1.11.6, the full public EMSCAD CSV was downloaded locally from a public GitHub raw mirror after the initially suggested mirror returned 404. The schema verified at 17,880 rows, 866 fraudulent labels, 17,014 legitimate labels, and the expected `company_profile`, `description`, `requirements`, `benefits`, and `fraudulent` columns.

The fixed heuristic risk score is useful for explainable triage but not accurate enough: on all 17,880 records at threshold 0.5 it produced 56.93% recall, 24.79% precision, and 34.54% F1. The deterministic trained TF-IDF logistic baseline in `pipeline/benchmarks/train_emscad_fraud_model.py` is stronger on the held-out 20% test split:

| Metric | Result |
| --- | ---: |
| Test records | 3,576 |
| Accuracy | 98.88% |
| Precision | 89.82% |
| Recall | 86.71% |
| F1 | 88.24% |
| False-positive rate | 0.50% |
| Top-50 FER before model penalty | 4.00% |
| Top-50 FER after model penalty | 0.00% |

This is a real improvement over the heuristic, but it is still not a 95% fraud benchmark. `pipeline/benchmarks/train_emscad_transformer_fraud.py` provides the stronger transformer training path. The first full local DeBERTa-v3-small run did not beat TF-IDF: 98.66% accuracy, 87.88% precision, 83.82% recall, 85.80% F1, and 0.59% false-positive rate.

For v1.11.8, the trainer was updated with structural metadata markers and class-weighted transformer loss. The weighted DeBERTa result improved over v1.11.7 but still did not beat the original TF-IDF baseline: 98.83% accuracy, 89.22% precision, 86.13% recall, 87.65% F1, and 0.53% false-positive rate. Adding the same metadata markers to TF-IDF increased precision but reduced recall: 98.88% accuracy, 92.36% precision, 83.82% recall, 87.88% F1, and 0.35% false-positive rate.

Precision-recall frontier checks show why this is not a threshold-only problem. On the held-out split, forcing recall to at least 95% drops the best observed precision to about 46-54% across TF-IDF/risk-score blends. A defensible 95% fraud claim now requires better labelled signal or a different model strategy, not just retuning the current classifiers.

The next fraud experiment should add external verification markers before training. `pipeline/benchmarks/external_verification_features.py` extracts company-domain, contact-email-domain, posting-URL, mismatch, liveness, and similarity markers from enriched job CSVs. Liveness checks are optional because they touch the network; when enabled, they deduplicate domains and URLs, use bounded concurrency with retry/backoff, and persist TTL-cached results. Transient network failures remain `unknown` and do not add fraud risk. The no-liveness mode is deterministic and suitable for CI or offline feature review. The fraud trainers automatically consume `verification_evidence_markers` and `verification_risk_score` when those columns exist.

`pipeline/benchmarks/external_provider_cache.py` is the required SQLite cache/rate-limit boundary for optional WHOIS, company-registry, and URL-reputation adapters. Providers must return verified evidence or `unknown`; absent credentials, timeouts, and provider errors must not become fraud evidence. `pipeline/benchmarks/evaluate_fraud_cascade.py` evaluates a recall-first sieve, structural verifier, and sparse-signal late fusion, and emits a label-free human fraud audit queue ordered by model disagreement.

`pipeline/benchmarks/codex_fraud_engine.py` adds train-only stateful domain-history and structural-clone evidence. Its blocklist requires at least three fraud observations and no legitimate observations; clone matches are continuous evidence by default, not an unconditional fraud label. The engine must be trained only on the training partition before evaluating a held-out partition.

For source-specific guard remediation, `pipeline/remediation/audit_expert_data.py` is the required fail-closed intake step for curated `hse_llm` and `cgoosen_combined` data. It accepts JSONL records with `source`, boolean `label`, and `text`; removes metadata artifacts, rejects duplicates and cross-label collisions, requires balanced class counts, and checks for label-correlated length imbalance before expert training.

```bash
cd pipeline
python ranking_evaluator.py /path/to/held-out.jsonl --min-top1 0.90 --min-ndcg 0.95
python benchmarks/export_emscad.py --input /path/to/fake_job_postings.csv --output ../.benchmark-data/emscad.jsonl
python fraud_evaluator.py ../.benchmark-data/emscad.jsonl --threshold 0.5 --top-k 50 --risk-penalty 0.8
python benchmarks/external_verification_features.py --input ../.benchmark-data/emscad.csv --output ../.benchmark-data/emscad.external.csv
python benchmarks/external_verification_features.py --input ../.benchmark-data/emscad.csv --output ../.benchmark-data/emscad.external.live.csv --check-liveness --timeout 2 --max-workers 4 --retries 2 --max-probes 250 --cache-path ../.benchmark-data/verification-liveness-cache.json
python benchmarks/train_emscad_fraud_model.py --input ../.benchmark-data/emscad.external.csv --output ../gateway/benchmarks/results/v1.11.9-emscad-tfidf-external-fraud.json --top-k 50 --risk-penalty 0.8
python benchmarks/train_emscad_fraud_model.py --input ../.benchmark-data/emscad.csv --output ../gateway/benchmarks/results/v1.11.8-emscad-tfidf-metadata-fraud.json --top-k 50 --risk-penalty 0.8
python benchmarks/train_emscad_transformer_fraud.py --input ../.benchmark-data/emscad.csv --output ../gateway/benchmarks/results/v1.11.8-emscad-deberta-weighted-fraud.json --base-model microsoft/deberta-v3-small --epochs 3
python benchmarks/build_ranking_judge_tasks.py --jobs /path/to/jobs.jsonl --candidates /path/to/candidates.jsonl --output ../.benchmark-data/ranking-judge-tasks.jsonl --max-jobs 100 --candidates-per-job 5
python benchmarks/build_ranking_audit_queue.py --input ../.benchmark-data/ranking-pair-scores.jsonl --output ../.benchmark-data/ranking-human-audit.jsonl --strategy stratified --disagreement-count 100 --top-count 50 --bottom-count 50
python benchmarks/train_transformer_guard.py --output ../.benchmark-data/mmbert-provenance-guard-smoke --provenance-jsonl ../.benchmark-data/provenance-pairs.jsonl --special-tokens ../.benchmark-data/provenance-special-tokens.json --limit-records 1000 --epochs 1 --stop-after-updates 5
python benchmarks/train_transformer_guard.py --output ../.benchmark-data/mmbert-provenance-guard --provenance-jsonl ../.benchmark-data/provenance-pairs.jsonl --special-tokens ../.benchmark-data/provenance-special-tokens.json --checkpoint-every-updates 250
```

## Latency

Local loopback benchmark, 1,000 requests, concurrency 20, stub upstream. Two consecutive release-candidate runs are shown to expose local variance:

| Run | Direct p50 | Gateway p50 | Added p50 | Added p95 | Added p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 11.9 ms | 36.4 ms | 24.5 ms | 28.3 ms | 64.1 ms |
| B | 12.9 ms | 44.1 ms | 31.2 ms | 69.3 ms | 68.2 ms |

The protected path includes authentication, JSON parsing, heuristic injection screening, PII detection/tokenization, proxying, and response restoration. It excludes real provider latency, TLS termination, Redis network latency, multi-host networking, and production logging. Results are a local development baseline, not an SLO.

Reproduce:

```bash
cd gateway
npm run benchmark:http -- 1000 20
npm run benchmark:latency -- 5000 20
```

## Reproducibility

Synthetic fingerprints remain useful for detecting deterministic regression, but they are not quality evidence. Public benchmark commands, dataset identifiers, sample counts, detector configuration, and raw JSON output should be retained with every future release.

## Unmeasured production areas

- The full proprietary PINT corpus has not been run, so Valence has no official PINT score.
- Kafka now has deterministic identities, idempotent production, Redis completion tracking, and a DLQ; measured consumer lag, replay tooling, and multi-region recovery remain open.
- Encryption at rest, retention policy, deletion workflow, and PDPA/GDPR control mapping depend on the operator's Kafka, Redis, object-store, and logging configuration and are not supplied as compliance guarantees by this repository.
- The HTTP latency run is local loopback, not multi-host sustained load.
- Real-world ranking accuracy remains unmeasured without independently labeled domain data.
