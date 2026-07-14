# Hybrid Human Review

This procedure creates the human-labelled evidence Valence does not yet have. It is deliberately separate from model training and from LLM pseudo-labels. The reviewer export contains source text, AI suggestions, and reviewer labels only; it never includes benchmark truth fields.

## Review rubrics

### PII

Review the complete text, not only highlighted spans. Mark every exposed sensitive span with the closest category. Set `pii_exposed` to `yes` when one or more spans remain exposed, `no` when none are present, and `uncertain` only when the approved policy cannot decide the label. Correct model spans by selecting text, changing labels, or deleting false positives.

### Ranking

Assess only supplied job and candidate evidence. `hard_eligibility` is `pass` when all demonstrated mandatory requirements are met, `fail` when a mandatory requirement is demonstrably unmet, and `unknown` when evidence is missing. Score role alignment and technical coverage from 1 through 4. `final_relevance` is 0 for mismatch, 1 for weak overlap, 2 for partial fit, and 3 for strong fit. Do not infer seniority, qualifications, protected attributes, or hiring outcomes.

## Build the blind review pack

For raw Markdown or poorly formatted source material, first create a fresh, offset-safe GLiNER task export. The exporter removes Markdown only when it is syntax, collapses whitespace into one deterministic line, runs GLiNER on that exact line, asserts `clean_text[start:end] == entity["text"]`, and logs/discards every invalid span.

```powershell
python -m pip install -r requirements-pii-classifier.txt
python scripts/export_gliner_label_studio.py raw-records.jsonl review-pack/gliner-tasks.json
```

Use `review/label-studio/pii-config.xml` when importing `gliner-tasks.json`. Never run inference on raw text and then display normalized text: the exporter's `data.text` is the same `clean_text` used by GLiNER.

PII source records and the prediction cache are local inputs. The builder strips `entities`, `truth`, and every other gold-label field before it writes a task. The default PII selection concentrates on spans with model confidence from 0.30 through 0.70. Add `--include-high-confidence-pii` only after that uncertainty queue is exhausted.

```powershell
python scripts/build_hybrid_review_pack.py `
  --pii-source .benchmark-data/nemotron-pii-test-1000.jsonl `
  --pii-predictions .benchmark-data/gretel-pii-v114-score-cache.jsonl `
  --pii-limit 500 `
  --output-dir review-pack
```

For ranking, provide an approved de-identified JSONL pair file. Each row must contain `job_id`, `candidate_id`, `job_text`, and `candidate_text`; it may also contain the bounded AI `ai_score` (0 through 3) and rationale. A release-pilot build rejects anything other than exactly 210 jobs with 10 to 20 unique candidates per job.

```powershell
python scripts/build_hybrid_review_pack.py `
  --ranking-pairs data/raw/approved-ranking-pairs.jsonl `
  --output-dir review-pack
```

Use `--allow-ranking-smoke` only for a non-release dry run. The output has separate `reviewer_a` and `reviewer_b` files. Import each into a separate Label Studio project; do not share reviewers, annotations, AI candidate order, or exports between projects.

## Label Studio

The repository includes a localhost-only, persistent Label Studio environment. Start it once:

```powershell
.\scripts\start_hybrid_review_env.ps1
```

Open `http://127.0.0.1:8081` and create the local Label Studio owner account. Create two separate PII projects named `Valence PII Reviewer A` and `Valence PII Reviewer B`; use [PII configuration](../review/label-studio/pii-config.xml), then import the printed Reviewer A or Reviewer B task file respectively. Do not share project access or exports between reviewers. The project storage is local-only under ignored `.valence-data/label-studio`.

Create ranking projects only after the approved 210-job pair file exists. Use [ranking configuration](../review/label-studio/ranking-config.xml) and the corresponding blind ranking task files. Reviewers must not see the AI rationale while deciding; remove that optional field from the input pair file if the UI exposes it.

Both reviewers label the 30 deterministic calibration jobs first. Export completed annotations as Label Studio JSON and reconcile them:

```powershell
python scripts/reconcile_hybrid_reviews.py `
  reviewer-a-export.json reviewer-b-export.json `
  --output-dir review-pack/reconciled
```

The command returns exit code 1 when ranking calibration Cohen's kappa is under 0.80. Tighten the rubric, repeat calibration, and freeze the rubric version before reviewing the remaining 180 jobs. PII disagreements and ranking disagreements are written to `needs-adjudication.json`; do not overwrite either independent review.

## Release evidence

After adjudication, convert the reconciled ranking labels to the existing `TalentEvaluationRecord` schema with stable pseudonymous identifiers, provenance hashes, and two preserved independent reviews. Then run the existing audit, manifest, and evaluator:

```powershell
python pipeline/talent_dataset_audit.py pilot-records.jsonl
python pipeline/talent_benchmark_manifest.py --help
python pipeline/talent_evaluator.py pilot-records.jsonl system-submissions.jsonl
```

The dataset is eligible only after every pilot case has two independent reviews, all material disagreements are adjudicated, the audit passes, and the manifest is frozen. This process creates evidence for model evaluation; it does not authorize autonomous employment decisions.
