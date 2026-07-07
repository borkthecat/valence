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
 |  pipeline/stage3           |   Candidate Hydrator and Fuzz Generator
 |  10,000+ profiles on demand |   controlled edge-case distribution
 +-----------------------------+
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
- Optional HS256 or RS256 JWT verification with required RBAC scopes and per-tenant request context.
- Per-tenant fixed-window rate limiting before payload parsing or upstream spend.
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

Self-contained stages, each of which runs its own verification and simulation routines directly. All environment-driven settings are read once through a cached loader in `pipeline/config.py`.

### Stage 3: Candidate Hydrator and Fuzz Generator

`pipeline/stage3_hydrator.py`. Pure standard library. Provides a `FuzzDataGenerator` that produces 10,000 or more randomized candidate profiles on demand with a controlled distribution of edge cases (5 percent structurally impossible ages, 5 percent unauthorized channels, 10 percent historical era anomalies). Its scale validation drives the full generated set through Stage 4 in batches and asserts that output ordering is identical across runs and that no disqualified profile ever reaches a result pool.

### Stage 4: Razor Reranking Engine

`pipeline/stage4_razor_reranker.py`. Pure standard library. Ingests up to 50 candidate profiles and reduces them to exactly 5. Each candidate starts at a base score of 100.0, with a fixed deterministic matrix across age plausibility, anniversary markers, channel authorization, colorway alignment, and historical era deviation. Unauthorized channels and structurally impossible values are disqualified outright and can never reach the final pool. A batch that cannot yield a clean pool fails closed rather than padding the result.

### Stage 5: Cognitive Verification Pass

`pipeline/stage5_cognitive_verifier.py`. Asynchronous FastAPI controller exposing `POST /v1/valence/stage5/verify`. Validates inbound payloads with strict Pydantic v2 schemas, sanitizes each profile against indirect injection and context poisoning, enforces a per-profile byte quota, and routes the request through the Valence Gateway over a non-blocking asyncio HTTP client with distributed trace headers. The result is an immutable, schema-validated verdict. Any upstream drop, connection failure, or security rejection triggers a fail-closed protocol that freezes the transaction and flags the tenant.

### Getting started

```
cd pipeline
python -m pip install -r requirements.txt

python stage3_hydrator.py
python stage4_razor_reranker.py
python stage5_cognitive_verifier.py
```

To serve the Stage 5 endpoint:

```
uvicorn stage5_cognitive_verifier:app --host 0.0.0.0 --port 8090
```

## Configuration

All configuration is environment-driven. Copy the template and edit it; the real `.env` is git-ignored so secrets never reach the repository.

```
cp .env.example .env
```

The gateway parses its variables through a type-safe Zod schema and refuses to boot on an invalid configuration. The pipeline reads its variables through a cached loader (`pipeline/config.py`). Key variables include `GATEWAY_PORT`, `UPSTREAM_PROVIDER_URL`, `GATEWAY_API_KEY`, `MAX_PAYLOAD_KB`, `TARGET_ERA`, `TARGET_CHANNEL`, and `AUTHORIZED_CHANNELS`. See [.env.example](.env.example) for the full list.

Two operational switches are worth calling out. Set `VALENCE_JSON_LOGS=true` to emit machine-readable structured log records (ISO timestamp, level, component, trace id, and a nested context object) for ingestion by Datadog, Splunk, or Cloud Logging; the human-facing dashboards remain unaffected. Set `MOCK_AI_PROVIDER=true` to intercept outbound verification calls locally with deterministic, schema-valid mock responses, which lets you drive very large sequential or concurrent load runs at zero external cost.

The gateway also exposes `GET /metrics` in Prometheus text format, protected by the gateway API key. Security-relevant events are written to `AUDIT_LOG_PATH` as hash-chained JSON lines unless the path is set to `off`; the log chain can be verified with the gateway audit verifier CLI.

## Running with Docker

Both components build into slim images and run together on an isolated bridge network, where the pipeline reaches the gateway by its service name:

```
cp .env.example .env
docker compose up --build
```

The gateway is exposed on port 8080 and the Stage 5 verification service on port 8090. The gateway image is a multi-stage Node build; the pipeline image runs its self-verifying stages under the strict warnings-as-errors flag as a build-time integrity gate.

## Unified demo

`run_system_demo.sh` starts the gateway in the background, runs the full analytical pipeline (Stage 3 fuzz generation through Stage 5 verification), prints each tool's dashboard, and cleans up all background processes on exit:

```
./run_system_demo.sh
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
python -W error stage3_hydrator.py
python -W error stage4_razor_reranker.py
python -W error stage5_cognitive_verifier.py
```

The pipeline also exposes a pytest suite that wraps these checks for CI discovery:

```
cd pipeline
pip install -r requirements-dev.txt
python -W error -m pytest -q
```

Stage 3/4 scale validation now drives 100,000 deterministic generated profiles through the reranker, and Stage 4 includes a synthetic oracle quality check for top-1 accuracy and top-5 recall.

### Continuous integration

Every push and pull request to `main` runs the workflow in [.github/workflows/ci.yml](.github/workflows/ci.yml), which builds and typechecks the gateway with a high-severity dependency audit, runs the pipeline test matrix under strict warnings-as-errors, and validates and builds the container topology.

## Security posture

- Fail-closed everywhere: any subsystem error removes candidates, blocks requests, or severs connections rather than degrading quietly.
- No secrets in source: the gateway reads all credentials from the validated environment and refuses to boot on an invalid configuration.
- Tamper-evident audit events: auth failures, rate limits, prompt blocks, fail-open bypasses, disconnects, and forwarded requests are recorded with a verifiable hash chain.
- Bounded work: every scanner rule uses bounded quantifiers, and streaming holdback is constant in stream length, so no payload can exhaust the event loop.
- Dependency hygiene: production dependencies are pinned with caret ranges and audited (`npm audit --omit=dev` reports zero vulnerabilities at release).

## Requirements

- Node.js 20 or newer for the gateway.
- Python 3.11 or newer for the pipeline (FastAPI and Pydantic v2 for Stage 5).

## License

Apache-2.0. See [LICENSE](LICENSE).

## Releases

The current release target is `v1.1.0`. See [RELEASE.md](RELEASE.md) for the preflight checklist and tag process.

## Authorship

Written, designed and developed by Arai Nanami Rachel.
