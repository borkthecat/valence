# Valence

Valence is a deterministic, multi-stage candidate identification and verification pipeline. It takes a large batch of hydrated candidate profiles, ranks them against a strict compliance and integrity matrix, and returns a small, high-confidence result set suitable for downstream decisioning. The pipeline is built for predictable behavior under load: identical inputs always produce identical outputs, and any integrity failure removes a candidate rather than degrading the result quietly.

## Pipeline stages

Valence is organized as a sequence of independent, composable stages.

### Stage 4: Razor Reranking Engine

`stage4_razor_reranker.py`

Ingests a batch of up to 50 candidate profiles and reduces it to exactly the top 5 high-integrity candidates. Each candidate starts from a base score of 100.0, and a fixed, fully deterministic matrix applies weighted adjustments across five dimensions:

- Age plausibility, with a hard penalty and disqualification for structurally impossible values.
- Anniversary edition markers.
- Channel authorization, where any unauthorized channel is disqualified outright and can never reach the final pool.
- Historical colorway alignment against the target.
- Historical era deviation, penalized in two bands by distance from the target year.

Disqualification is a hard gate applied before ranking. A batch that cannot yield a full pool of clean candidates fails closed rather than padding the result with disqualified profiles. The engine ships with an embedded operational dashboard and a built-in verification suite.

### Stage 5: Cognitive Verification Pass

`stage5_cognitive_verifier.py`

An asynchronous verification controller that adjudicates the Stage 4 pool down to a single winner. It exposes a FastAPI endpoint (`POST /v1/valence/stage5/verify`), validates every inbound payload against strict Pydantic v2 schemas, and applies a contextual sanitizer that neutralizes indirect injection and context-poisoning attempts and enforces a per-profile byte quota before any profile is compiled into the evaluation context.

Verification requests are routed through a non-blocking HTTP client built on native asyncio primitives, with OpenTelemetry-style trace headers propagated end to end. The adjudicated result is returned as an immutable, schema-validated verdict containing the selected winner, a bounded confidence coefficient, a qualitative justification, and a mitigation log. A fallback parser recovers cleanly from partial or malformed upstream output.

Any upstream drop, connection failure, or downstream security rejection triggers a strict fail-closed protocol: the transaction is frozen, the tenant is flagged, and unverified profiles are prevented from leaking downstream. The module includes a live observability dashboard and a 20-way concurrent, multi-tenant load simulation that exercises nominal, degraded, and hostile paths.

## Requirements

- Python 3.11 or newer.
- Stage 4 has no third-party dependencies.
- Stage 5 requires FastAPI and Pydantic v2.

```
pip install "fastapi>=0.115" "pydantic>=2.9"
```

## Running

Each stage is self-contained and runs its own verification and simulation routines directly:

```
python stage4_razor_reranker.py
python stage5_cognitive_verifier.py
```

Both modules run cleanly under the strict warnings-as-errors flag:

```
python -W error stage4_razor_reranker.py
python -W error stage5_cognitive_verifier.py
```

To serve the Stage 5 verification endpoint:

```
uvicorn stage5_cognitive_verifier:app --host 0.0.0.0 --port 8090
```

## Design principles

- Deterministic scoring: no randomness in the ranking path, with stable tie-breaking.
- Fail-closed by default: integrity failures remove candidates and freeze transactions rather than passing uncertain results through.
- Strict schema boundaries: every inbound and outbound structure is validated and immutable once produced.
- Observable by construction: each stage renders live operational telemetry.

## Authorship

Written, designed and developed by Arai Nanami Rachel.
