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

PII source records and a prediction cache are accepted only when every source record carries a stable ID and that ID matches a prediction record exactly. Positional source/cache matching is rejected. The builder strips `entities`, `truth`, and every other gold-label field before it writes a task. The default PII selection concentrates on spans with model confidence from 0.30 through 0.70, balances those tasks across predicted categories, and prioritizes scores nearest 0.50. Add `--include-high-confidence-pii` only after that uncertainty queue is exhausted.

For the local calibration workflow, use the offset-validated GLiNER export instead. Every retained span is checked against its displayed normalized text, and the builder rejects malformed, duplicate, or reviewer/gold-contaminated tasks.

```powershell
python scripts/build_hybrid_review_pack.py `
  --pii-label-studio-tasks .benchmark-data/review-pack-gliner-v1.13.5/gliner-tasks.json `
  --pii-limit 30 `
  --pii-calibration-count 30 `
  --output-dir .benchmark-data/review-pack-pii-offset-validated-calibration-30
```

Audit any import file before it reaches Label Studio:

```powershell
python scripts/audit_pii_label_studio_tasks.py .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-tasks-reviewer_a.json
```

For ranking, provide an approved de-identified JSONL pair file. Each row must contain `job_id`, `candidate_id`, `job_text`, and `candidate_text`; it may also contain the bounded AI `ai_score` (0 through 3) and rationale. A release-pilot build rejects anything other than exactly 210 jobs with 10 to 20 unique candidates per job.

```powershell
python scripts/build_hybrid_review_pack.py `
  --ranking-pairs data/raw/approved-ranking-pairs.jsonl `
  --output-dir review-pack
```

Use `--allow-ranking-smoke` only for a non-release dry run. The output has separate `reviewer_a` and `reviewer_b` files. Import each into a separate Label Studio project; do not share reviewers, annotations, AI candidate order, or exports between projects.

## Label Studio

The repository includes a localhost-only, persistent Label Studio environment. Start the default 30-task calibration pack:

```powershell
.\scripts\start_hybrid_review_env.ps1
```

Use `-PiiLimit 500 -RebuildPiiPack` only after the calibration rubric is stable and the full PII review pass is required.

Open `http://127.0.0.1:8081` and create the local Label Studio owner account. Create two separate PII projects named `Valence PII Reviewer A` and `Valence PII Reviewer B`; use [PII configuration](../review/label-studio/pii-config.xml), then import the printed Reviewer A or Reviewer B task file respectively. Do not share project access or exports between reviewers. The project storage is local-only under ignored `.valence-data/label-studio`.

Do not import `review-pack-pii-v1.13.5-calibration-30`; its suggestions were generated from an unsafe source/cache pairing and are invalid for review.

### Independent AI first pass

An AI can create silver suggestions, but it cannot replace a human-labelled release set. Export a blind packet with no existing GLiNER suggestions, upload that file to the AI tool, then save the AI response as JSON. The importer computes offsets locally from exact quoted text and rejects mismatches, unknown records, overlaps, missing records, and unsupported labels.

```powershell
python scripts/export_pii_ai_annotation_packet.py `
  .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-tasks-reviewer_a.json `
  .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-ai-input.json
```

To annotate the complete 1,000-record GLiNER export, use this source and output path instead:

```powershell
python scripts/export_pii_ai_annotation_packet.py `
  .benchmark-data/review-pack-gliner-v1.13.5/gliner-tasks.json `
  .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-input-1000.json
```

Give the AI this instruction along with `pii-ai-input.json`:

```text
Return only a JSON array. Preserve every record_id exactly. For each record, return
{"record_id":"...","entities":[{"label":"PERSON_NAME","text":"exact substring","occurrence":1}]}.
Allowed labels: PERSON_NAME, EMAIL, PHONE, ADDRESS, API_KEY, PASSWORD, SSN, CREDIT_CARD, GENERIC_SECRET.
Quote entity text exactly as it appears in text. Do not return offsets, explanations, Markdown, or any other fields.
Use an empty entities array when there is no PII.
```

Import the response as silver suggestions, never as ground truth:

```powershell
python scripts/import_pii_ai_annotations.py `
  .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-tasks-reviewer_a.json `
  .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-ai-output.json `
  .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-ai-silver-tasks.json `
  --model-version external-ai-silver `
  --discard-implausible
python scripts/audit_pii_label_studio_tasks.py .benchmark-data/review-pack-pii-offset-validated-calibration-30/pii-ai-silver-tasks.json
```

When the original GLiNER task export is unavailable, rebuild the normalized source from the deterministic Nemotron JSONL before importing the AI response. The command rejects any ID mismatch.

```powershell
python scripts/build_pii_ai_annotation_source.py `
  .benchmark-data/nemotron-pii-test-1000.jsonl `
  .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-source-1000.json `
  --expected-annotations C:/Users/reade/Downloads/pii-ai-output-final.json
```

Import the complete response with the conservative silver filter and persist the quality report:

```powershell
python scripts/import_pii_ai_annotations.py `
  .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-source-1000.json `
  C:/Users/reade/Downloads/pii-ai-output-final.json `
  .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-silver-filtered-1000.json `
  --model-version external-ai-silver-final `
  --discard-implausible `
  --quality-report .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-silver-quality-1000.json
python scripts/audit_pii_label_studio_tasks.py .benchmark-data/review-pack-gliner-v1.13.5/pii-ai-silver-filtered-1000.json
```

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
