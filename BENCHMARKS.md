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

v1.11.2 uses 15 revision-pinned corpora and 21,485 test records. A corpus passes only when accuracy, precision, recall, and F1 are each at least 95% and false-positive rate is no more than 5%.

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

A local policy-aware transformer experiment using `jhu-clsp/mmBERT-base`, train-only validation calibration, and separate `direct`, `indirect`, and `secret` policy thresholds reached 9/15 strict gates. That is useful evidence that policy separation improves the architecture, but it is not enough to claim production-grade 95% coverage. Additional train-only synthetic augmentation and two public off-the-shelf prompt-injection classifiers did not beat the 9/15 result on this matrix, so the release remains a research preview until a stronger independently validated guard reaches the target.

The corpora do not share one perfect definition of injection. Some label roleplay as malicious while others deliberately include roleplay as benign, several are synthetic or translated derivatives, and small sets have wide confidence intervals. Valence records those disagreements instead of tuning per-dataset rules against observed test labels.

Valence ships the 4.97 MB JSON guard as the local default and also supports bounded local and HTTP `GuardModelClient` integrations for independently trained enterprise models. HTTP guard services receive the normalized text and a policy value of `direct`, `indirect`, or `secret`. The compact artifact is pinned by SHA-256. Lakera's complete 4,314-input PINT corpus includes proprietary data and is not publicly downloadable, so Valence does not claim a full PINT score.

```bash
python -m pip install -r requirements-benchmark.txt
python pipeline/benchmarks/prepare_injection_matrix.py --output .benchmark-data/injection-matrix
python pipeline/benchmarks/run_injection_matrix.py --matrix .benchmark-data/injection-matrix/matrix.json --model gateway/models/prompt-injection-guard.json --output .benchmark-data/injection-matrix/report.json --repetitions 3 --timeout-seconds 120
python pipeline/benchmarks/train_guard_model.py --output .benchmark-data/candidate-guard.json
python -m pip install -r requirements-transformer.txt
python pipeline/benchmarks/train_transformer_guard.py --output .benchmark-data/mmbert-policy-guard
python pipeline/benchmarks/calibrate_transformer_guard.py --model .benchmark-data/mmbert-policy-guard
python pipeline/benchmarks/evaluate_transformer_guard.py --matrix .benchmark-data/injection-matrix/matrix.json --model .benchmark-data/mmbert-policy-guard --output .benchmark-data/injection-matrix/mmbert-policy-report.json
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

```bash
cd pipeline
python ranking_evaluator.py /path/to/held-out.jsonl --min-top1 0.90 --min-ndcg 0.95
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
