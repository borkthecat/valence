# Talent Integrity Reference Application

Talent Integrity is the first domain implementation of Valence Core. It is not required to use the security gateway and it must not autonomously reject applicants.

## Decision layers

1. **Eligibility gate:** explicit hard requirements supplied by the role owner. Missing evidence is not silently treated as failure.
2. **Evidence validation:** provenance, consistency, freshness, and verification status for each claimed signal.
3. **Relevance ranking:** required/preferred skill coverage, relevant experience and recency, seniority, location, compensation, and certifications where lawful.
4. **Risk adjustment:** fraud, impersonation, internal inconsistency, and unsupported claims. Risk cannot be overwhelmed by a high relevance score.
5. **Fairness evaluation:** measured separately from relevance; protected attributes and obvious proxies are not ranking features.
6. **Bounded LLM review:** structured findings for ambiguous profiles only, followed by deterministic policy and human review.

The target formulation is `relevance + evidence reliability - fraud risk - uncertainty`, with hard eligibility outside the score. The current Stage 4 product-identification fields (`colorway`, `anniversary`, and historical era) are legacy research-preview schema and must not be presented as a talent ranking model. They remain temporarily for benchmark compatibility only.

## Pilot foundation

The versioned canonical data and evaluation-output contract is implemented in
`pipeline/talent_schema.py`; the separate offline evaluator is in
`pipeline/talent_evaluator.py`. Neither replaces the legacy research pipeline
or makes an employment recommendation.

- [Pilot annotation protocol](TALENT_INTEGRITY_ANNOTATION.md)
- [Delivery roadmap](TALENT_INTEGRITY_ROADMAP.md)

## Stage 5 contract

Use `POST /v1/valence/stage5/review`. It returns one judgment per candidate:

The Stage 5 process is an internal service. Both `/review` and `/verify` share the same strict request schema, field quotas, injection sanitizer, gateway-routed upstream client, trace propagation, bounded timeout/retry behavior, fail-closed handling, audit events, and metrics. Production deployments must expose neither route directly; place the service behind the authenticated, rate-limited Valence Gateway or an equivalent private service boundary.

```json
{
  "candidate_id": "c17",
  "eligibility": "eligible",
  "evidence_consistency": 0.91,
  "relevance_adjustment": 0.04,
  "risk_findings": [],
  "uncertainties": ["UNCERTAINTY_MISSING_REQUIRED_EVIDENCE"],
  "explanation": "Certification date could not be verified.",
  "recommended_action": "hold_for_review"
}
```

The top-level contract includes `schema_version: "1.0"` and `decision_mode: "advisory_review"`. Each candidate contains separate `model_assessment` and `policy_outcome` objects. Valence validates that every pool member appears exactly once. Code includes only clean `eligible` + `shortlist` findings in `recommended_shortlist`; any uncertainty, risk, model-originated ineligibility, unknown eligibility, or review recommendation sets `human_review_required=true`. Neither output is a final hiring action.

The older `/verify` endpoint selects one winner and is retained only for compatibility with non-employment experiments. It is deprecated for Talent Integrity integrations, will not receive new Talent Integrity features, and returns `Deprecation: true` with a documentation link. No removal date is declared yet.

## End-to-end enterprise example

```text
ATS export -> canonical adapter -> POST /stage5/review
          -> model assessments -> deterministic policy outcomes
          -> shortlist + human review queue -> reviewer decision -> ATS audit record
```

The adapter supplies role requirements and candidates containing stable IDs, evidence-backed skills, experience history, certifications, constraints, and provenance. Until a versioned talent schema replaces the legacy research schema, these belong in bounded `attributes` and `signals` fields and must not be inferred from protected data.

`pipeline/talent_adapters.py` provides deterministic CSV, JSON, and JSONL pre-label intake. It requires stable case, job, and candidate IDs, rejects duplicate case/candidate keys, normalizes skills and bounded experience, and emits separate source and canonical SHA-256 digests. Example:

```bash
python pipeline/talent_adapters.py --input /approved/ats-export.csv --output .benchmark-data/talent-import.jsonl --manifest .benchmark-data/talent-import-manifest.json --source-system approved-ats
```

The adapter intentionally does not create labels. `pipeline/fairness_invariants.py` can assert that controlled name, email, phone, or pronoun mutations do not change a supplied deterministic decision function; this is a regression check, not legal or statistical fairness certification.

The ATS, not Valence, stores the final action:

```json
{
  "candidate_id": "c17",
  "reviewer_id": "recruiter-42",
  "action": "advance_to_interview",
  "reason_code": "HUMAN_EVIDENCE_CONFIRMED",
  "valence_schema_version": "1.0"
}
```

Valence deliberately ignores protected attributes, photographs, names as demographic signals, and historical hiring outcomes as automatic labels. The ATS retains the final employment decision, notice, appeal, and legally required record.
