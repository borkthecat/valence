# Valence Threat Model

Status: research-preview baseline. Review this document whenever a trust boundary, storage backend, authentication mode, or upstream provider changes.

## Assets

- Plaintext prompts, candidate profiles, credentials, identifiers, and restored model responses.
- Token-vault mappings and per-request restoration scopes.
- Tenant identity, policy configuration, model outputs, review decisions, and audit records.
- Signing, encryption, gateway, provider, Redis, and Kafka credentials.

## Trust boundaries and plaintext access

The client and domain adapter originate plaintext. The gateway process sees plaintext while scanning and tokenizing it. Redis stores token mappings when the shared vault is enabled and must therefore be treated as sensitive infrastructure. The upstream provider should receive only the policy-approved, tokenized request. The gateway sees the upstream response while performing request-scoped restoration. Kafka workers see ingested profile fields. Operators with process-memory, Redis, or credential access are privileged actors.

```text
Client --plaintext--> Gateway tokenizer --surrogates--> Upstream LLM
Client <--plaintext-- Gateway restoration <--surrogate response-- Upstream LLM
                         |                         |
                    token vault              provider boundary
```

```text
Trusted role fields ----\
Untrusted candidate text +--> policy/sanitizer --> model boundary --> findings
Retrieved evidence -----/                              |
Future OCR text (untrusted) ---------------------------/
findings --> deterministic policy --> human-review boundary --> ATS decision
                 |                         |
             metrics only          append-only audit boundary
```

## Actors

- Authenticated tenants and their application operators.
- Valence gateway, pipeline, and infrastructure administrators.
- Upstream model and external-verification providers.
- Malicious callers, compromised tenants, hostile retrieved content, insiders, and supply-chain attackers.

## STRIDE analysis

| Threat | Example | Existing control | Residual risk / required action |
| --- | --- | --- | --- |
| Spoofing | Forged tenant identity | API keys or JWT validation, scoped tenant context | Rotate credentials; prefer asymmetric JWTs and external secret management |
| Tampering | Profile, queue, or audit mutation | Strict schemas, fingerprints, idempotency keys, hash-chained audit entries | Hash chains do not prevent deletion; export logs to immutable external storage |
| Repudiation | Operator denies an override | Structured events and audit chain | Human override identity and reason must be retained by the integrating system |
| Information disclosure | Redis theft or cross-request restoration | Request-scoped surrogates, TTLs, tenant tests | Redis compromise exposes live mappings; isolate, encrypt, authenticate, and minimize TTL |
| Denial of service | Oversized payload, retry storm, poisoned Kafka record | Payload limits, rate limits, bounded retries, DLQ, fail closed | Fail-closed dependencies can block valid traffic; measure dependency rejection SLOs |
| Elevation of privilege | Tenant supplies permissive policy or admin scope | Schema and authorization checks | Tenant-configurable policies require allowlisted bounds and separation of duties |

## Key abuse cases

1. Retrieved documents instruct the model to ignore policy or exfiltrate secrets.
2. A tenant attempts to restore a surrogate created by another tenant or request.
3. A compromised Redis instance reads live token mappings.
4. An upstream provider returns malformed, partial, or adversarial output.
5. A profile embeds instructions in descriptions, attributes, URLs, or future OCR text.
6. An operator deletes audit files or uses an over-permissive tenant configuration.
7. Stage 5 output is treated as an autonomous hiring rejection.

## Control decisions

- Security failures fail closed; the resulting valid-request rejection rate is an operational SLO.
- Stage 5 `/review` returns bounded findings. Deterministic code derives a non-binding shortlist; ambiguity and negative findings require human review.
- OCR, if introduced, is untrusted retrieved content and must traverse provenance-aware injection screening.
- Secrets belong in an external secret manager in production and require documented rotation and revocation drills.
- Audit logs must be shipped to append-only or retention-locked storage; the local hash chain only detects modification.

## Compromise blast radius

- Gateway process: current in-flight plaintext, configured provider credentials, and reachable vault mappings.
- Redis: mappings retained within the configured TTL across gateway instances using that Redis deployment.
- Kafka: profile data in retained topics for tenants sharing that cluster.
- Tenant credential: that tenant's allowed routes and quotas, unless authorization isolation is defective.

Use separate credentials and infrastructure per environment, isolate high-sensitivity tenants where required, and test restoration and authorization isolation on every release.

## Out of scope today

Endpoint malware, a fully compromised host/kernel, provider-side retention guarantees, legal suitability for automated employment decisions, physical security, multi-region recovery, and semantic attacks not represented in the pinned evaluation corpora.
