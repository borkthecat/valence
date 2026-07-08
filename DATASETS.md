# Evaluation Datasets

Valence does not treat synthetic scale tests as real-world accuracy evidence. External datasets are downloaded at evaluation time and are not redistributed in release archives.

## Amazon Shopping Queries (ESCI)

- Owner: Amazon Science
- Source: https://github.com/amazon-science/esci-data
- License: Apache-2.0
- Labels: manually annotated Exact, Substitute, Complement, and Irrelevant query-product judgments
- Scale: 1,118,011 judgments in the reduced ranking version and 2,621,288 in the larger version
- Use: held-out product-ranking evaluation in English, Japanese, and Spanish

`pipeline/benchmarks/export_esci.py` retrieves the test split through the Hugging Face datasets server mirror, computes label-blind lexical relevance, and emits Valence evaluation JSONL. ESCI labels are consumed only by `ranking_evaluator.py` after ranking.

## Gretel PII Masking English

- Owner: Gretel.ai
- Source: https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1
- License: Apache-2.0
- Scale: approximately 60,000 synthetic, span-annotated English records
- Use: training and evaluating a PII classifier connected through `PII_CLASSIFIER_URL`

Valence supplies the secure classifier client and benchmark contract. Model training remains a separate, versioned ML process so weights, tokenizer, dataset revision, calibration thresholds, and model cards can be reviewed independently of the gateway.

## deepset Prompt Injections

- Owner: deepset
- Source: https://huggingface.co/datasets/deepset/prompt-injections
- License: Apache-2.0
- Scale: 662 labeled benign and injection prompts
- Use: public PINT-compatible detector evaluation

`pipeline/benchmarks/export_deepset_injections.py` emits JSONL accepted by `gateway/benchmarks/injectionBenchmark.ts`. `train_deepset_guard.py` trains the bundled bounded multinomial model only on the training split; the 116-case test split remains evaluation-only.

## Excluded Defaults

Amazon Berkeley Objects is useful for multi-view product research but is CC BY-NC 4.0. AI4Privacy's current dataset license restricts commercial use and redistribution. Neither dataset is bundled, trained on, or presented as an enterprise-safe default.
