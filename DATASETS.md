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

## Prompt-Injection Matrix

The v1.11.x matrix evaluates 15 revision-pinned public corpora. Official test splits are preserved; train-only corpora receive a deterministic, class-stratified 80/20 split. Normalized test hashes are excluded from candidate training across every source. Matrix reports group corpora into direct attack, indirect/provenance, and secret-exfiltration suites.

| Dataset | Revision | Declared license |
| --- | --- | --- |
| `wambosec/prompt-injections` | `071ee17a60112b7f9f808398156b430aadfaf1d2` | MIT |
| `deepset/prompt-injections` | `4f61ecb038e9c3fb77e21034b22511b523772cdd` | Apache-2.0 |
| `Shomi28/prompt-injection-dataset` | `0146454c8404a347ccc170a0291bcec932252fef` | MIT |
| `jackhhao/jailbreak-classification` | `2f2ceeb39658696fd3f462403562b6eea5306287` | Apache-2.0 |
| `cgoosen/llm_guard_dataset` | `b18903ecf0bd6e95ef6f1cdfb691dae7df2851e4` | Apache-2.0 |
| `neuralchemy/Prompt-injection-dataset` | `7d70432dfcf47a821612cbf9d34e9d9e3ad20e75` | Apache-2.0 |
| `wambosec/prompt-injections-subtle` | `cd789a6e362aa72624d7f835c5270c8c3bdaf524` | MIT |
| `jcanode/safeguard-prompt-injection` | `61fbe3588450fa9b47ac1176ca7b5d2cc932344c` | Apache-2.0 |
| `rikka-snow/prompt-injection-multilingual` | `f1ad1f3dd44581f53a4c67e96a9dde2fb419ee5b` | MIT |
| `beratcmn/turkish-prompt-injections` | `c40c38f8ca632052fbfec19e90fab31fce33eda1` | Apache-2.0 |
| `S-Labs/prompt-injection-dataset` | `002a9dd18514abd021869823d6b0429b38606d99` | MIT |
| `cgoosen/prompt_injection_combined` | `483296fde129d392d73077ad0c5d1175087cd9aa` | MIT |
| `Smooth-3/llm-prompt-injection-attacks` | `dd47798b64ebf0e833ecdbff6b1d73be3e440581` | Apache-2.0 |
| `darkknight25/Prompt_Injection_Benign_Prompt_Dataset` | `a0fc54fb563468a7fd64a9412718ce7cdb366666` | MIT |
| `hse-llm/prompt-injections` | `6619b5e0f7a907404b8b81df6aa97c2114dd27a1` | MIT |

These corpora differ in language, generation method, and labeling policy. Some treat roleplay as an attack while others use roleplay as benign material; several contain synthetic or translated examples. The matrix therefore reports every corpus separately and never uses a pooled score to override a failed dataset gate.

Dataset files are downloaded only for local benchmarking and are not included in Valence releases. The checked-in report contains aggregate metrics, not source records. Review each dataset card and license before using downloaded data outside this benchmark.

## NotInject

- Owner: leolee99 / InjecGuard authors
- Source: https://huggingface.co/datasets/leolee99/NotInject
- Revision used by exporter: `847ae76cf8fea5ed325429e569ae8cfef022d2e0`
- Scale: 339 benign prompts across `NotInject_one`, `NotInject_two`, and `NotInject_three`
- Use: over-defense evaluation for benign prompts containing injection-like trigger words

`pipeline/benchmarks/export_notinject.py` exports all records as benign JSONL cases with suite `over_defense`. Valence uses this as an evaluation set, not as bundled training data.

## EMSCAD Fake Job Postings

- Owner: University of the Aegean / EMSCAD
- Source: http://emscad.samos.aegean.gr/
- Common mirror: https://www.kaggle.com/datasets/shivamb/real-or-fake-fake-jobposting-prediction
- Scale: 17,880 job postings, including 866 fraudulent postings
- Use: candidate/job profile fraud baseline and Fraud Exposure Rate evaluation

`pipeline/benchmarks/export_emscad.py` maps EMSCAD rows into Valence rich-profile records with `fraudulent`, `risk_score`, and `source_relevance_score` fields. `pipeline/fraud_evaluator.py` measures fraud precision, recall, F1, false-positive rate, and Fraud Exposure Rate before and after risk-adjusted reranking. The full CSV is not bundled; only a small EMSCAD-shaped fixture is checked in for CI smoke coverage.

`pipeline/benchmarks/train_emscad_fraud_model.py` trains a deterministic TF-IDF logistic baseline against a local EMSCAD CSV. `pipeline/benchmarks/train_emscad_transformer_fraud.py` trains a stronger DeBERTa-style sequence classifier path for the same CSV. v1.11.6 used a local public raw mirror only to reproduce aggregate metrics; the raw CSV is ignored by git and not redistributed by this project.

## Excluded Defaults

Amazon Berkeley Objects is useful for multi-view product research but is CC BY-NC 4.0. AI4Privacy's current dataset license restricts commercial use and redistribution. Neither dataset is bundled, trained on, or presented as an enterprise-safe default.
