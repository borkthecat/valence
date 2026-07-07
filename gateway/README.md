# Valence Gateway

An open-source, zero-trust AI Security Gateway Proxy for LLM traffic. Valence Gateway sits inline between your applications and an upstream LLM provider, enforcing a strict fail-closed security model against the OWASP Top 10 for LLM Applications: prompt injection screening on the way in, PII and secret tokenization before anything leaves your trust boundary, and streaming surrogate reconstitution on the way back.

Built with Node.js 20+, TypeScript (maximum strictness), Express, Axios, and Zod. Stateless across requests except for a single in-memory token vault with a hard 5-minute TTL.

## How it works

```
 Client app                Valence Gateway                       LLM Provider
 ----------                ------------                       ------------
     |  POST /v1/...  [gateway key]                                 |
     |------------------->|                                         |
     |                    | 1. auth (constant-time key check)       |
     |                    | 2. injection shield (block at 403)      |
     |                    | 3. PII scan: raw -> [M_EMAIL_9f2c...]   |
     |                    | 4. forward masked body [provider key]   |
     |                    |---------------------------------------->|
     |                    |             streamed response           |
     |                    |<----------------------------------------|
     |                    | 5. reconstitute: [M_EMAIL_...] -> raw   |
     |<-------------------|    (chunk-boundary safe)                |
     |   restored stream  |                                         |
```

Key properties:

- The client credential never reaches the provider. The provider credential never reaches the client.
- Raw PII and secrets never reach the provider. The provider only ever sees opaque surrogates backed by 64 bits of CSPRNG entropy each.
- Vault entries evict on a hard 5-minute TTL with per-entry timers, so the plaintext-to-surrogate mapping is short-lived and memory is bounded.
- Restoration is scoped per request: a response stream may only resolve the surrogates minted for its own request. Even if a foreign surrogate with a live vault entry appears in a response, it is treated as unknown, so concurrent clients can never receive one another's data.
- Every scanner regex uses bounded quantifiers (RFC-derived caps for emails, fixed ceilings for key formats), so no payload can trigger catastrophic backtracking on the single-threaded event loop.
- Upstream requests are cancelled the moment the client disconnects, so an abandoned stream cannot keep consuming provider tokens or hold sockets open.
- Every subsystem failure is governed by SECURITY_MODE. Under FAIL_CLOSED (the default and the only recommended production posture), a broken scanner blocks traffic instead of passing it unscanned.
- Mid-stream failures sever the socket rather than closing the stream cleanly, so a truncated response can never masquerade as a complete one.

## OWASP LLM Top 10 coverage

| Risk | Control |
| --- | --- |
| LLM01 Prompt Injection | Weighted heuristic shield (instruction override, persona jailbreaks, control-token smuggling, exfiltration asks) plus a pluggable guard-model tier |
| LLM02 Sensitive Information Disclosure | PII/secret tokenization with Luhn and SSA semantic validation; vault TTL bounds exposure |
| LLM04 Denial of Service | Body size limits, credential length caps, bounded streaming holdback (O(1) memory per stream) |
| LLM06 Excessive Agency / data exfil | Markdown image beacon and tool-result forgery rules in the shield |
| LLM08 Supply chain (keys) | Provider key isolated server-side; client keys checked in constant time |

## Quick start

```bash
npm install
npm run build

PORT=8443 \
UPSTREAM_PROVIDER_URL=https://api.anthropic.com \
UPSTREAM_API_KEY=<provider key> \
GATEWAY_API_KEY=<random 32+ char secret> \
SECURITY_MODE=FAIL_CLOSED \
npm start
```

Then point your application at the gateway instead of the provider:

```bash
curl -N http://localhost:8443/v1/messages \
  -H "x-valence-key: <your GATEWAY_API_KEY>" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-6","stream":true,"messages":[{"role":"user","content":"Draft a reply to alice@example.com"}]}'
```

The provider receives `Draft a reply to [M_EMAIL_9f2c41d0a7b3e815]`; your client receives the restored address in the streamed response.

## Configuration

All configuration is validated at boot with Zod. An invalid environment terminates the process with exit code 1 before a socket is bound. Variable names and constraint messages are printed on failure; values never are.

| Variable | Required | Constraint | Description |
| --- | --- | --- | --- |
| `PORT` | no (default 8443) | integer 1-65535 | Listen port |
| `UPSTREAM_PROVIDER_URL` | yes | https only (http allowed for loopback) | Provider base URL |
| `UPSTREAM_API_KEY` | yes | min 16 chars | Credential the gateway presents upstream |
| `GATEWAY_API_KEY` | yes | min 32 chars | Credential clients present to the gateway |
| `SECURITY_MODE` | no (default FAIL_CLOSED) | FAIL_CLOSED or FAIL_OPEN | Subsystem failure posture |
| `NODE_ENV` | no (default production) | development, test, production | Log verbosity and hardening profile |

### SECURITY_MODE semantics

SECURITY_MODE governs what happens when an internal control (scanner, shield, reconstitution) throws. It never affects verdicts: a blocked prompt is blocked in both modes.

- `FAIL_CLOSED`: subsystem failure rejects the request (502 with a generic reason code) or severs the stream if already in flight. Use this in production, always.
- `FAIL_OPEN`: subsystem failure forwards traffic unscanned and logs a SECURITY BYPASS event. Exists solely for controlled evaluation environments. The gateway prints a persistent warning at boot when this mode is active.

## Endpoints

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /healthz` | none | Liveness probe; discloses nothing about configuration |
| `POST /v1/*` | gateway key | Proxied completion endpoints (path is forwarded to the provider) |

Authentication accepts either header form:

- `x-valence-key: <key>`
- `Authorization: Bearer <key>`

Comparison is constant-time (SHA-256 digest both sides, then `crypto.timingSafeEqual`). Missing, malformed, oversized, and wrong credentials all produce a byte-identical generic 401.

## Error contract

Clients receive machine-readable reason codes and a request id, never internal messages or stack traces.

| Code | Status | Meaning |
| --- | --- | --- |
| `PROMPT_REJECTED` | 403 | Injection shield verdict (includes rule ids and score) |
| `INVALID_REQUEST_SHAPE` | 400 | Body failed schema validation |
| `SECURITY_SUBSYSTEM_FAILURE` | 502 | Scanner or shield failed under FAIL_CLOSED |
| `STREAM_RECONSTITUTION_FAILURE` | 502 | A surrogate in the response had no vault entry (e.g. TTL expiry mid-stream) |
| `UPSTREAM_UNREACHABLE` | 502 | Provider connection or timeout failure |
| `REQUEST_REJECTED` | 4xx | Transport-layer rejection (e.g. body too large) |
| `GATEWAY_INTERNAL_FAILURE` | 500 | Anything else; fail-closed default |

If the failure occurs after response headers were sent, there is no status code to change, so the gateway destroys the connection outright. Treat an aborted stream as a failed request and retry.

## Zero-trust deployment parameters

- Terminate TLS in front of the gateway (load balancer or sidecar). The gateway itself speaks plain HTTP and must never be exposed directly.
- Generate `GATEWAY_API_KEY` with at least 256 bits of entropy (`openssl rand -base64 48`) and rotate it on your normal credential schedule. Rotation is a restart: the gateway is stateless apart from the short-lived vault.
- Run one gateway instance per provider credential. Sticky routing is required if you scale horizontally, because the token vault is per-process: a surrogate minted on instance A cannot be restored by instance B. Route by session affinity or run the gateway as a per-application sidecar.
- Set `SECURITY_MODE=FAIL_CLOSED`. Alert on any `SECURITY BYPASS` log line; in FAIL_CLOSED it cannot occur.
- Give the process a restart supervisor. Uncaught exceptions and unhandled rejections deliberately exit non-zero (an unprovable gateway must not keep serving).
- Log pipeline: auth headers and cookies are redacted at the logger level; shield telemetry contains truncated excerpts only; PII findings are logged as categories and counts, never values.

## Known limitations (stated, not hidden)

- Surrogate reconstitution operates on the raw byte stream. A surrogate split across two separate SSE events (interleaved with `data:` framing) requires a provider-specific delta codec to reassemble; same-stream and same-event splits are fully handled. If your provider tokenizes surrogates apart across events, add a delta-parsing adapter in front of the reconstructor.
- JavaScript strings cannot be zeroed in place. Scrubbing drops every reference (WeakMap registry plus explicit buffer clearing), which is the strongest guarantee the runtime offers. If byte-level erasure is a hard requirement, the text channel must remain in Buffers end to end.
- The vault is in-memory by design. A crash loses pending mappings, which fails safe: the client sees a severed stream, never someone else's data.
- Heuristic detection is a floor, not a ceiling. Wire real `ClassifierClient` and `GuardModelClient` implementations for the cognitive tier; the Null clients ship so the composition stays uniform.

## Development

```bash
npm run dev        # watch mode
npm run typecheck  # strict compile, no emit
npm test           # vitest
npm run lint       # eslint
```

## License

Apache-2.0
