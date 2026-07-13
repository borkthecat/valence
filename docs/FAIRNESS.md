# Fairness and Human Review Policy

Valence is decision support, not an autonomous rejection system. Deployments must provide notice, a qualified reviewer, an override reason, and an appeal or correction path appropriate to local law.

## Feature policy

Do not rank on sex, gender identity, ethnicity, nationality, religion, disability, age, name, address, photograph, or other protected attributes except where a documented legal purpose permits separate fairness evaluation. Audit proxies including school prestige, postal location, employment gaps, language style, and historically learned outcome labels. Fraud and eligibility claims require evidence and must not infer protected status.

## Evaluation before decision impact

- Double-label an initial 200 cases and adjudicate disagreements.
- Report NDCG@5, qualified-candidate Recall@5, pairwise agreement, eligibility violations, unsupported-evidence promotion, and fail-closed rate.
- Establish human-human agreement; interpret model agreement relative to that ceiling.
- Predeclare job-family, seniority, region, language, and legally permitted protected-group slices.
- Run counterfactual pairs that change names, pronouns, age cues, schools, locations, gaps, and disability cues without changing job-relevant evidence.
- Measure selection-rate and error-rate gaps with confidence intervals; do not hide slices in a pooled score.

## Human review record

Store the input version, system version, findings, evidence references, reviewer identity, action, reason, override, timestamps, and any appeal outcome. Hiring outcomes can encode historical bias and must not automatically become training labels.

## Decision responsibility

| Actor | May recommend | May shortlist | May reject |
| --- | --- | --- | --- |
| Stage 4 rules | Yes | Yes, within configured policy | Only explicit hard eligibility |
| LLM verifier | Yes, as findings | No binding action | No |
| Valence policy engine | Yes | Yes | Only configured deterministic rules |
| Human reviewer | Yes | Yes | Yes, under organization policy and applicable law |
