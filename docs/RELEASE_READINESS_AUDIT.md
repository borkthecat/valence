# Release Readiness Audit — 2026-07-13

Scope: review of `d39dd17` against `origin/main`, followed by a live Docker validation and the corrective commit `b2f50f2`. This is an evidence-based research-preview assessment, not a compliance certification.

## Commit review

The architectural split and advisory review contract are directionally correct. The audit found and corrected two policy-boundary defects: model-originated `ineligible` findings now always require human review, and duplicate candidate IDs are rejected during request validation rather than after a model call. The latter is tested in-process and through the Docker API.

No local filesystem links, generated source files, stale product version references, or secret-like values were found in tracked source. The raw public datasets are not retained in the repository; result artifacts and dataset/model revisions are retained, but independent reproduction still requires downloading the pinned public inputs. This is appropriate for licensing but is not archival reproducibility.

The review endpoint is exercised through HTTP under the mock provider. It is not authenticated itself; it is an internal service and must remain behind the authenticated, rate-limited gateway or an equivalent private network boundary. It has not been tested end to end against a non-mock upstream, real ATS source, or persistent review queue.

## Product assessment

| Area | Strong now | Research-grade / enterprise blocker | Highest realistic level without new architecture or data |
| --- | --- | --- | --- |
| Core gateway | Request-scoped restoration, tenant tests, fail-closed streaming, strict schemas, audit chain | Key rotation, vault revocation, outage/recovery evidence, multi-host SLOs | Strong gateway research preview; limited deployment after shadow operations evidence |
| Injection guard | Per-corpus reporting, provenance routing, train-only calibration, negative benchmark honesty | Indirect/secret coverage, NotInject over-defense, public corpora do not represent production tool traffic | Useful review/telemetry guard, not autonomous enterprise blocker |
| PII/tokenization | Scoped vault, streaming reconstruction, email performance, leakage tests | Exact span F1 55.3%, weak phone/SSN coverage, English-only default evaluation | Secure transport mechanism; detector remains experimental |
| Talent Integrity | Bounded review contract, explicit human boundary, EMSCAD fraud baseline, ranking evaluator | Legacy product schema, no independently adjudicated candidate-job data, no reviewer workflow | Safe orchestration demonstration, not a validated ranker |

More infrastructure, ranking fields, synthetic profiles, generic LLM size, or dashboards should be deferred. They would not repair missing labels, weak attack distribution coverage, or absent operational evidence. Raw multimodal processing should also wait for an OCR threat/cost model.

## Benchmark validity

The repository does well at separating synthetic regression from external evaluation and reports per-corpus injection results. The main remaining validity risks are:

- Normalized exact-text deduplication does not remove semantic near duplicates, translations, or template families across corpora.
- Public injection corpora have inconsistent definitions of roleplay, indirect injection, and secret exfiltration; pooled scores are therefore descriptive only.
- Small sources (for example 60, 94, 98, and 115 cases) have wide uncertainty and cannot support tight per-source claims.
- ESCI is product search, not candidate ranking; it only validates evaluator mechanics and a lexical baseline.
- EMSCAD is dated binary job-posting fraud data. Random stratified splits can leak company, template, URL, or campaign style across train and test; group/time splits are needed before deployment claims.
- Threshold calibration appears train/validation separated in the reviewed trainers, but each result needs a persisted split manifest and dataset checksum to prove the exact partition.
- Result JSON retains aggregate metrics and model hashes but not raw inputs. Public source revisions are pinned; a reproducibility bundle should add input manifests, normalized-record hashes, split hashes, commands, dependency lock hashes, and run environment.

## Scorecard targets

Targets are gates, not pooled averages. A target needs sufficient positive and negative counts to give a useful confidence interval; require at least 100 positives and 100 negatives per critical slice before claiming a percentage threshold, and report Wilson intervals.

| Subsystem | Research preview | Shadow / limited production | Enterprise automatic enforcement |
| --- | --- | --- | --- |
| Direct injection | recall/F1 >=95%; benign FPR <=3% | high-severity recall >=97%, F1 >=93%, FPR <=2% | recall >=98%, F1 >=95%, FPR <=1% |
| Indirect, tool, retrieved, secret, multilingual, obfuscated | each recall >=90%; 12/15 gates | each F1 >=93%; 13/15 gates; repeated-run stability | each F1 >=95%; 14/15 gates; no critical slice <90% recall |
| Benign trigger prompts | NotInject-equivalent FPR <=5% | <=2% and human review routing | <=1%, per-source <=3% |
| PII / secrets | email, keys, cards >=99% recall; ID >=97%; phone >=95%; compatible recall/span P/F1 >=95% | same by declared locale plus shadow false-negative review | same with 100% restoration correctness, zero leakage, and no sensitive observability output |
| Talent ranking | NDCG@5 >=.75, Recall@5 >=90%, pairwise >=80%, top-1 >=70% | independently labelled shadow agreement and 0 hard-eligibility violations | NDCG@5 >=.85, Recall@5 >=95%, pairwise >=90%, top-1 >=80% or within 5 points of human-human agreement |
| Fraud block | no claim from EMSCAD alone | review recall >=95%, precision >=50%, FPR <=3%, calibrated scores | auto-block precision >=98%, FPR <=.1%, top-ranked Fraud Exposure Rate 0% |
| Reliability | local latency only | p50/p95/p99 <30/75/150 ms, declared throughput, dependency fail-closed rate | >=99.9%, multi-host soak/recovery, zero silent restoration corruption |

Top-1 ranking agreement remains secondary: several candidates can be equivalently qualified. Recall@k, NDCG, pairwise agreement, eligibility violations, and human disagreement are more decision-useful.

## Required data

| Dataset | Minimum and labeling | Stratification / holdout | Unlocks |
| --- | --- | --- | --- |
| Talent pilot | 200 jobs, 10–20 candidates/job; two independent reviewers and third adjudicator | job family, seniority, region, language, completeness, adversarial text | schema repair, human agreement, initial error taxonomy |
| Talent benchmark | 1,000–2,000 jobs under the same labels: eligibility, graded relevance 0–3, evidence sufficiency, fraud, reason | organization/time holdout; never train on evaluation jobs | NDCG, Recall@5, pairwise and subgroup claims |
| Injection shadow corpus | >=500 positives and >=500 benign records per critical direct/indirect/secret slice; same text with provenance changes | source family and time holdout; human dual review for ambiguous cases | real policy thresholds and over-defense gates |
| PII locale suites | >=500 examples/entity/locale for Singapore, US, UK, EU, Japan; character offsets and sensitivity class | template/entity family holdout | per-locale recall and span claims |
| Fraud evidence set | current postings with independently verified fraud labels, company/domain/email/URL/liveness evidence | group by company/domain/campaign and time | calibration, cascade thresholds, block/review claims |
| Shadow production | versioned opt-in events, reviewer decision, override, outcome, cost and outage markers | immutable holdout windows; labels never inferred from hiring outcome alone | operational and drift validation |

Every release dataset needs a card, license, collection period, provenance/checksum, annotator instructions, adjudication log, split manifest, and contamination audit.

## Enterprise capability gates

| Capability | Required by |
| --- | --- |
| Private authenticated reviewer action API, queue persistence, reviewer identity/authorization, override audit trail, retention/deletion API, tenant policy versions/rollback, shadow mode, cost and review-rate reporting | Shadow deployment |
| Appeals/correction workflow, model/policy rollback drills, canonical ATS adapters, drift and reviewer-disagreement monitoring, key rotation/vault revocation, backup/restore and Kafka replay tests | Limited production |
| Multi-region recovery, canary deployment, compliance-control mapping, SBOM, signed images/provenance attestations, disaster-recovery testing, independently validated automatic enforcement | Enterprise automatic enforcement |
| Additional dashboards, raw multimodal/OCR processing, more synthetic generators, autonomous candidate rejection | Future / defer |

## Roadmap

1. **Immediate pre-PR:** keep the two audited fixes, add Docker live smoke to CI, and publish a reproducibility manifest for each benchmark. This is release-blocking because current live coverage is manual and artifacts lack complete split/input manifests. Risk: low engineering, moderate CI/environment risk.
2. **Next research milestone:** create the 200-case double-adjudicated Talent Integrity set. Build the canonical schema and evaluator slices before adding ranking features. Expected impact: converts ranking from unmeasured to interpretable. Risk: labeling quality and consent, not code complexity.
3. **Next security milestone:** collect provenance-contrastive, tool/retrieval, multilingual/obfuscated exfiltration, and benign trigger-heavy shadow data. Train only on training partitions; evaluate by source and policy. Expected impact: indirect/secret recall and FPR, currently the main guard blockers. Risk: data quality and label disagreement.
4. **Next production milestone:** implement a persistent reviewer workflow plus shadow deployment, policy/model rollback, cost accounting, failure SLOs, and restart/replay tests. Expected impact: measures review workload, outages, and real false blocks. Risk: integration and data governance.
5. **Enterprise-readiness milestone:** only after independent offline and shadow gates pass, add multi-host performance, retention/deletion, recovery, supply-chain attestations, and approved automatic enforcement policy. Risk: high operational/compliance burden.

## Scores

| Dimension | Score / 100 | Basis |
| --- | ---: | --- |
| Architecture | 82 | Clear security boundaries; talent schema is still legacy |
| Security design | 84 | Strong scoped tokenization and fail-closed posture; operational controls incomplete |
| Security-model effectiveness | 60 | Direct performance useful; indirect, secret, and benign FPR fail enterprise gates |
| PII protection | 58 | Restoration design is strong; default detector measured far below required span quality |
| Ranking validity | 25 | No real candidate-job ground truth |
| Fraud detection | 66 | Solid EMSCAD baseline, insufficient current/generalizable evidence |
| Testing/reproducibility | 80 | Broad tests and pinned public sources; incomplete reproducibility manifests and live CI |
| Observability | 68 | Metrics/audit foundations, no real operational SLO/drift evidence |
| Enterprise operability | 42 | Docker/Kafka/Redis topology exists; reviewer, recovery, and lifecycle controls absent |
| Governance/fairness | 55 | Good policy documents; controls are not operationalized |
| Documentation | 84 | Honest and clear; some implementation remains aspirational |
| Product clarity | 76 | Core/reference-app split is much clearer, but legacy schema confuses the talent story |

Overall: **76/100 research preview**, **48/100 shadow readiness**, **30/100 enterprise production**. After the independently adjudicated talent pilot plus provenance/over-defense security milestone: realistically **82–85 research preview** and **60–65 shadow readiness**. Higher scores depend on real labelled and shadow data, not more generic code.
