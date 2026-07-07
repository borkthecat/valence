# Valence

Valence is a zero-trust processing platform for high-stakes candidate identification. It pairs a deterministic, multi-stage identification pipeline with an inline security gateway so that every profile is scored, verified, and adjudicated behind a strict fail-closed boundary. Sensitive data is tokenized before it ever leaves the trust boundary, and any integrity failure at any layer removes the candidate rather than letting an uncertain result pass through.

The platform ships as a single package with two cooperating components:

| Component | Path | Language | Role |
| --- | --- | --- | --- |
| Valence Gateway | `gateway/` | TypeScript / Node.js 20+ | Inline zero-trust security proxy for the model traffic |
| Valence Pipeline | `pipeline/` | Python 3.11+ | Deterministic candidate ranking and cognitive verification |

## Architecture

```
 Stage 3 hydrated candidates
            |
            v
 +-----------------------------+
 |  pipeline/stage4            |   Razor Reranking Engine
 |  deterministic scoring      |   up to 50 candidates in, exactly 5 out
 +-----------------------------+
            |
            v
 +-----------------------------+        +-----------------------------+
 |  pipeline/stage5           |  --->  |  gateway/                   |
 |  Cognitive Verification    |  proxy |  Valence Gateway            |
 |  async controller          |  <---  |  auth, injection screening, |
 +-----------------------------+        |  PII tokenization, streaming|
            |                           +-----------------------------+
            v
   single verified winner
```

Stage 4 reduces a large candidate batch to a small high-integrity pool. Stage 5 adjudicates that pool down to a single winner, routing the request through the Valence Gateway, which authenticates the caller, screens for injection, tokenizes any sensitive values before they reach the upstream model, and restores them in the streamed response.

## Valence Gateway (`gateway/`)

An inline, stateless reverse proxy that enforces a fail-closed security model for LLM traffic. It mitigates the OWASP Top 10 for LLM Applications:

- Constant-time credential verification on every request.
- Injection screening (instruction override, persona jailbreaks, control-token smuggling, exfiltration attempts) with bounded, backtracking-safe rules.
- PII and secret tokenization against an in-memory vault with a hard five-minute TTL. The upstream provider only ever sees opaque surrogates.
- Per-request restoration scope, so a response can only restore the surrogates minted for its own request. Concurrent callers can never receive one another's data.
- Streaming surrogate reconstitution that survives arbitrary chunk and byte boundary splits.
- A fail-closed error boundary that scrubs sensitive buffers, and severs the connection outright on mid-stream failure so a truncated response can never look complete.

### Getting started

```
cd gateway
npm install
npm run build

PORT=8443 \
UPSTREAM_PROVIDER_URL=https://api.anthropic.com \
UPSTREAM_API_KEY=<provider key> \
GATEWAY_API_KEY=<random 32+ char secret> \
SECURITY_MODE=FAIL_CLOSED \
npm start
```

Point your application at the gateway instead of the provider:

```
curl -N http://localhost:8443/v1/messages \
  -H "x-valence-key: <your GATEWAY_API_KEY>" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","stream":true,"messages":[{"role":"user","content":"Draft a reply to alice@example.com"}]}'
```

The provider receives the masked surrogate; your client receives the restored address in the streamed response. Full configuration, endpoint, and deployment reference lives in [gateway/README.md](gateway/README.md).

## Valence Pipeline (`pipeline/`)

Two self-contained stages, each of which runs its own verification and simulation routines directly.

### Stage 4: Razor Reranking Engine

`pipeline/stage4_razor_reranker.py`. Pure standard library. Ingests up to 50 candidate profiles and reduces them to exactly 5. Each candidate starts at a base score of 100.0, with a fixed deterministic matrix across age plausibility, anniversary markers, channel authorization, colorway alignment, and historical era deviation. Unauthorized channels and structurally impossible values are disqualified outright and can never reach the final pool. A batch that cannot yield a clean pool fails closed rather than padding the result.

### Stage 5: Cognitive Verification Pass

`pipeline/stage5_cognitive_verifier.py`. Asynchronous FastAPI controller exposing `POST /v1/valence/stage5/verify`. Validates inbound payloads with strict Pydantic v2 schemas, sanitizes each profile against indirect injection and context poisoning, enforces a per-profile byte quota, and routes the request through the Valence Gateway over a non-blocking asyncio HTTP client with distributed trace headers. The result is an immutable, schema-validated verdict. Any upstream drop, connection failure, or security rejection triggers a fail-closed protocol that freezes the transaction and flags the tenant.

### Getting started

```
cd pipeline
python -m pip install -r requirements.txt

python stage4_razor_reranker.py
python stage5_cognitive_verifier.py
```

To serve the Stage 5 endpoint:

```
uvicorn stage5_cognitive_verifier:app --host 0.0.0.0 --port 8090
```

## Testing

The gateway ships an executable smoke suite covering the vault, security filters, streaming reconstitution, audit hardening, and a full in-process end-to-end run against a stub provider:

```
cd gateway
npm test
```

Each pipeline stage self-verifies on execution and runs cleanly under the strict warnings-as-errors flag:

```
cd pipeline
python -W error stage4_razor_reranker.py
python -W error stage5_cognitive_verifier.py
```

## Security posture

- Fail-closed everywhere: any subsystem error removes candidates, blocks requests, or severs connections rather than degrading quietly.
- No secrets in source: the gateway reads all credentials from the validated environment and refuses to boot on an invalid configuration.
- Bounded work: every scanner rule uses bounded quantifiers, and streaming holdback is constant in stream length, so no payload can exhaust the event loop.
- Dependency hygiene: production dependencies are pinned with caret ranges and audited (`npm audit --omit=dev` reports zero vulnerabilities at release).

## Requirements

- Node.js 20 or newer for the gateway.
- Python 3.11 or newer for the pipeline (FastAPI and Pydantic v2 for Stage 5).

## License

Apache-2.0. See [LICENSE](LICENSE).

## Authorship

Written, designed and developed by Arai Nanami Rachel.
