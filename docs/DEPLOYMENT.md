# Enterprise Deployment Modes

## 1. Gateway only

An existing LLM application points its provider-compatible route at Valence Core. The client authenticates with an API key or scoped JWT. The gateway scans provenance, tokenizes detected PII and secrets, forwards approved content, restores only request-scoped surrogates, and emits metrics and audit events. The gateway need not deploy the talent pipeline.

Data is held in process for the request and in the token vault for its configured TTL. Provider retention remains governed by the provider contract. Security rejection returns a 4xx response; dependency or unreadable-stream failure terminates or returns an error rather than a plausible partial success.

## 2. API ranking

An ATS adapter sends one role and a bounded candidate set using the canonical Talent Integrity schema described in [TALENT_INTEGRITY.md](TALENT_INTEGRITY.md). Hard eligibility is evaluated before relevance. Stage 4 returns a shortlist; Stage 5 `/review` adds structured findings and uncertainties. The integrating ATS owns the source record, retention period, reviewer identity, override, appeal, and final action.

## 3. Batch ingest

An ATS or approved adapter publishes a batch through the ingestion API. Valence validates records, adds deterministic identities, and writes Kafka messages. Workers stage a complete batch in Redis, isolate poison records in the DLQ, and produce Stage 5-ready pools. Operators must set Kafka retention, Redis TTL, DLQ access, replay authorization, and deletion rules to match the tenant agreement.

## Adapter boundary

Workday, Greenhouse, Lever, Ashby, CSV, and HR-XML representations must be converted outside the policy engine. An adapter is responsible for field mapping, units, locale, provenance, and explicit missingness; it must never invent eligibility or evidence. New adapters should emit the canonical schema and pass contract fixtures before being advertised as supported.

## Required production configuration

- TLS at ingress and to remote Redis/Kafka/provider endpoints.
- Scoped JWTs or independently rotated tenant credentials.
- External secret storage and a rotation runbook.
- Authenticated, encrypted Redis and Kafka with environment isolation.
- Append-only audit export and declared retention/deletion periods.
- Human-review ownership, escalation, appeal, and outage procedures.
- Shadow deployment and measured SLOs before any decision impact.
