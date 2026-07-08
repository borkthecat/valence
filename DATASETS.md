# Evaluation Datasets

Valence does not treat synthetic scale tests as universal accuracy evidence. Large source datasets are downloaded at evaluation time; small held-out fixtures are redistributed only when their declared licenses permit reproducible evaluation.

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
- Use: cross-dataset detector evaluation and training

The 546-case training split contributes to the bundled model. The 116-case test split remains evaluation-only and is checked separately to expose distribution shift.

## WamboSec Prompt Injections

- Owner: Wambo Security
- Source: https://huggingface.co/datasets/wambosec/prompt-injections
- Declared license: MIT
- Scale: 5,189 training prompts and 577 test prompts; 2,340 benign and 3,426 malicious overall
- Use: primary English prompt-injection training and held-out release evaluation

The source card says prompts were generated with LLMs across multiple attack techniques. The test split is therefore useful, larger, and independently published, but it is still synthetic and does not establish accuracy on private production traffic. `train_guard_model.py` pins WamboSec revision `071ee17a60112b7f9f808398156b430aadfaf1d2`, deepset revision `4f61ecb038e9c3fb77e21034b22511b523772cdd`, and every source-file SHA-256 digest. It removes normalized duplicates, rejects conflicting labels, and fails if any normalized training prompt appears in either reserved test split.

## Excluded Defaults

Amazon Berkeley Objects is useful for multi-view product research but is CC BY-NC 4.0. AI4Privacy's current dataset license restricts commercial use and redistribution. Neither dataset is bundled, trained on, or presented as an enterprise-safe default.
