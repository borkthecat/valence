# Benchmark completion plan

This is the decisive path from the v1.13.4 research preview to measured shadow readiness. A pooled score never overrides a failed critical slice. Human-labelled and production-shadow evidence is intentionally last because the remaining repository-side controls and evaluators already exist.

## Current decision table

| Area | Current evidence | Research gate | Decision |
| --- | --- | --- | --- |
| PII exact span | Five-fold GLiNER + heuristic calibration: 74.58% precision, 69.03% recall, 71.70% F1 across all 4,314 declared spans; heuristic 94.49% precision and 24.25% recall | precision/recall/F1 >=95%; entity recall targets by type | Keep advisory; person and generic identifier spans remain below release gates |
| NotInject Compact | 61.65% benign accuracy, 38.35% FPR | FPR <=5% | Do not use Compact as an autonomous blocker |
| PIGuard reference | 88.50% benign accuracy, 11.50% FPR | FPR <=5% | Better baseline, still not a release candidate without Valence-policy fine-tuning |
| V6 cascade shadow candidate | 97.29% accuracy, 96.55% precision, 95.39% recall, 95.97% F1, 1.75% FPR pooled; two secret-policy slices fail | direct recall/F1 >=95%; weak suites >=90% recall; benign FPR <=5% | Use for shadow/review routing only; freeze a threshold on new labels before promotion |
| EMSCAD fraud | Group holdout: 97.26% accuracy, 90.15% precision, 64.32% recall, 75.08% F1, 0.48% FPR; zero group overlap | review recall >=95%; auto-block precision >=98% and FPR <=0.1% | Precision-first triage only; random-split 88.48% F1 is not deployment evidence |
| Talent ranking | Candidate-job accuracy unmeasured; ESCI evaluator baseline NDCG@5 0.562 | pilot NDCG@5 >=0.75, Recall@5 >=90%, pairwise >=80%, top-1 >=70% | No ranking quality claim until the human pilot is frozen |

## Work order

1. **PII evidence expansion.** The broad GLiNER service, production adapter, score calibration, and fail-closed gate are implemented. Supply Singapore, US, UK, EU, and Japan evaluation sets with at least 500 examples per gated entity and locale. Use the persisted gate unchanged and reject models that improve recall through overlapping or shifted spans.
2. **Guard replacement.** Retire Compact from automatic enforcement. Fine-tune the V6/PIGuard-class transformer on train-only benign trigger prompts paired with direct, indirect, retrieved, secret-exfiltration, multilingual, and obfuscated attacks. Pass provenance as metadata or special tokens, never an untrained text prefix. Calibrate on validation data, then freeze thresholds before NotInject and the 15-corpus test matrix.
3. **Fraud evidence.** Enrich current, permissioned job postings with company-domain liveness, email/domain mismatch, posting URL status, RDAP age, registry status, and verified clone history. Use company/domain/campaign groups and a later time window as the test split. Unknown provider responses stay unknown, never fraudulent.
4. **Human ranking pilot.** Run the exact workflow below. Do not train on the pilot. Use it to choose error priorities and to decide whether a larger 1,000-2,000-job benchmark is justified.
5. **Shadow proof.** Run the candidate guard, fraud cascade, and ranking submission side by side with existing operations for at least one frozen window. Log recommendations only. Measure overrides, review rate, false blocks, drift, latency, dependency failure, and restoration errors.

## Human-labelled ranking pilot

1. Obtain approval for 210 real jobs and their candidate pools. Reserve 10 jobs for reviewer calibration and 200 for the pilot. Aim for 10-20 candidates per job; record smaller real pools rather than adding synthetic candidates.
2. Export only job requirements and candidate evidence permitted for evaluation. Remove names, email, phone, addresses, photos, protected attributes, and irrelevant free text. Replace source documents with approved references and SHA-256 content hashes.
3. Convert every case to `TalentEvaluationRecord` schema v1.1. Give stable pseudonymous `case_id`, `job_id`, and `candidate_id` values. Populate explicit hard requirements, claims, evidence links, policy version, jurisdiction, source provenance, and `split: "pilot"`.
4. Recruit two independent reviewers and one adjudicator. Keep the reviewer identity map outside the dataset. Record conflict-of-interest exclusions before assignment.
5. Run the 10 calibration jobs. Each reviewer labels every candidate independently: hard eligibility (`pass/fail/unknown`), relevance (0-3), evidence sufficiency, inconsistency risk, human-review-required, explanation, and confidence. Discuss rubric ambiguity, revise the rubric once, and exclude these cases from system metrics.
6. Freeze the rubric version. Assign the 200 pilot jobs blind: reviewers cannot see each other's labels, system scores, candidate order from Valence, or hiring outcomes.
7. Send material disagreements to the third adjudicator. Preserve both original reviews. Store the resolved label separately with reason, adjudicator ID, and timestamp. Never overwrite an independent review.
8. Freeze all cases only after two complete reviews and any required adjudication. Run `python pipeline/talent_dataset_audit.py pilot-records.jsonl`; fix duplicate IDs, cross-split evidence reuse, digest errors, policy mixing, and incomplete coverage before scoring.
9. Create and sign the pre-registration manifest with dataset digest, split, metrics, thresholds, exclusions, model/policy digests, evaluation commit, and bootstrap seed using `pipeline/talent_benchmark_manifest.py`.
10. Generate one `TalentEvaluationSubmission` per case using the frozen Valence version. Preserve the complete deterministic ranking, candidate assessments, reason codes, policy/model versions, and reproducibility metadata.
11. Run `python pipeline/talent_evaluator.py pilot-records.jsonl system-submissions.jsonl`. Report NDCG@5, Recall@5, pairwise agreement, top-1, hard-eligibility violations, routing precision/recall, reviewer agreement, denominators, and case-resampled confidence intervals.
12. Promote only if the confidence-supported result meets the pilot gates and has zero hard-eligibility violations. Otherwise label the top error clusters, modify only the training split or deterministic policy, and rerun on a new untouched test set.

## Inputs only the operator can supply

- Permissioned, current job/candidate records and a lawful retention/deidentification basis.
- Two qualified independent reviewers plus a third adjudicator.
- Current shadow traffic and confirmed outcomes for injection and fraud evaluation.
- Credentials or approved feeds for registry, reputation, and domain-verification providers.
- A deployment environment for sustained SLO, restart, backup/restore, and recovery testing.

Everything else in this plan is repository-side and should be automated or enforced in CI.
