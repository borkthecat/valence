# Project Blockers

This is the current production punch list for Valence. It separates engineering blockers from tooling or release-process issues.

## Domain Call

Valence should take candidate/job profiles as the first real domain. That matches the existing Stage 3 through Stage 5 profile pipeline and lets one evaluation stream cover ranking quality, fraud resistance, and adversarial profile text. Product matching has better public benchmarks, but it would validate a different product unless Valence is repositioned around commerce listings.

## Priority 1: Guard Model Provenance Gap

The compact bundled guard is not enterprise-grade yet. It passes 5/15 strict prompt-injection corpus gates, but the suite rollup shows the real distribution:

| Suite | F1 | Primary failure |
| --- | ---: | --- |
| Direct attack | 95.23% | near gate, still corpus-sensitive |
| Indirect / provenance | 81.95% | low recall |
| Secret exfiltration | 75.76% | low precision and recall |
| Over-defense / NotInject | 61.36% accuracy | benign trigger-word false positives |

PIGuard reproduces its upstream NotInject behavior when evaluated canonically on raw prompts: 88.50% over-defense accuracy and 11.50% false positives. The same model fails when Valence prepends `[VALENCE_CONTEXT=direct]`, so the next model task is not a generic threshold search. It is provenance-aware fine-tuning or a wrapper that passes provenance as metadata instead of text.

Required next work:

1. Fine-tune PIGuard-style training with benign trigger-word examples and Valence provenance tags.
2. Re-run direct, indirect/provenance, secret-exfiltration, and over-defense suites separately.
3. Keep block and review thresholds separate; do not collapse results into a single pooled score.

Current implementation support:

- `pipeline/benchmarks/generate_provenance_pairs.py` creates contrastive examples where identical payload text receives different labels based on structured provenance.
- `gateway/src/core/filters/provenanceRouting.ts` maps provenance boundaries to guard policies and minimum model scores.
- The gateway applies provenance routing to user-session and retrieved tool content without prepending Valence tags to the text sent to the guard model.

## Priority 2: Real Candidate/Job Profile Evaluation

The synthetic profile generator proves deterministic behavior, not real-world accuracy. Candidate/job profiles need a public, independently labeled starting point before claiming production accuracy.

Use EMSCAD as the first external dataset because it provides 17,880 real job postings with 866 manually confirmed fraudulent records. It is binary fraud data, not ranking data, so it should become the first fraud/safety benchmark rather than the final ranking benchmark.

Required next work:

1. Add an EMSCAD importer that converts job postings into Valence rich-profile records.
2. Define a fraud/risk label contract separate from Stage 4 ranking relevance.
3. Measure precision, recall, F1, and false-positive rate against EMSCAD before adding private labels.
4. Build a separate ranking dataset only after the fraud baseline is reproducible.

Current implementation support:

- `pipeline/benchmarks/export_emscad.py` converts EMSCAD CSV rows into Valence rich-profile JSONL with fraud labels and bounded risk scores.
- `pipeline/fraud_evaluator.py` measures binary fraud metrics and Fraud Exposure Rate before and after risk-adjusted reranking.
- The checked-in EMSCAD fixture is only a smoke sample; the full public CSV is still required for a release-grade result.

## Priority 3: Indirect Injection Needs Schema, Not Just More Data

Indirect injection is weak because untrusted text is currently represented as prompt text plus a policy tag. Real attacks depend on source: user message, system instruction, tool output, retrieved document, profile description, source link, or image OCR text.

Required next work:

1. Carry provenance as structured fields in benchmark records.
2. Train/evaluate guards with provenance metadata preserved.
3. Add fixtures where the same text is benign in a user request but hostile in tool output.
4. Measure tagged versus untagged performance to prove the schema helps.

## Priority 4: Multimodal Evidence Is Metadata-Only

Valence accepts image metadata and URLs, not raw image bytes. That is good for security and cost, but it means the current system cannot detect hidden text inside images unless OCR is added deliberately.

Required next work:

1. Decide whether images will ever be sent to an LLM or OCR model.
2. If yes, add bounded OCR extraction and treat OCR text as untrusted retrieved content.
3. If no, keep image work focused on evidence integrity: HTTPS, MIME, size, hash, duplicates, liveness, and provenance.

## Current Score

Valence is approximately 78/100 as an open-source research preview. It is architecturally serious and reproducible, but it is not yet enterprise-grade because the guard model is not validated across provenance-aware indirect injection, secret exfiltration, and benign trigger-word over-defense, and the profile-ranking pipeline still lacks real candidate/job labels.
