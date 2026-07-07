/**
 * Valence Gateway - Global Fail-Closed Error Boundary
 *
 * The last line of the FAIL_CLOSED invariant: when ANY gateway subsystem
 * throws, the request must die safely. "Safely" decomposes into three
 * obligations, in order:
 *
 *  1. SCRUB   - every sensitive transient registered for the request
 *               (reconstructor buffers, staged body copies) is cleared
 *               before anything else happens, so a failure path can never
 *               retain more plaintext than the success path.
 *  2. SEVER   - if headers were already sent (mid-stream failure) the
 *               response CANNOT be trusted to look like an error, so the
 *               socket is destroyed outright. A truncated body on an
 *               aborted connection is unambiguous to every HTTP client;
 *               a truncated body on a cleanly closed 200 stream is a
 *               silent data-integrity lie.
 *  3. SIGNAL  - if headers were NOT sent, the client receives a generic,
 *               reason-coded JSON body. Internal messages, stack traces,
 *               and payload fragments never cross the boundary.
 *
 * Telemetry receives structured metadata only (error class, request id,
 * route, phase) - never bodies, credentials, or raw error messages from
 * unknown error types, since those routinely embed request payloads.
 */

import { randomUUID } from 'node:crypto';
import type { ErrorRequestHandler, Response } from 'express';
import { PiiScanError } from '../core/filters/piiScanner';
import { InjectionShieldError } from '../core/filters/injectionShield';
import { UnresolvedSurrogateError } from '../core/streaming/chunkReconstructor';

/* -------------------------------------------------------------------------
 * Sensitive-trace registry
 * ---------------------------------------------------------------------- */

/**
 * Anything holding transient sensitive material for the lifetime of one
 * request. `scrub()` must be idempotent and must never throw usefully -
 * the boundary swallows scrub failures because scrubbing is best-effort
 * cleanup on a path that is already failing.
 */
export interface SensitiveTrace {
  scrub(): void;
}

/**
 * WeakMap keyed by Response: entries become collectable the moment the
 * response object does, so an abandoned request cannot pin its traces.
 */
const traceRegistry = new WeakMap<Response, Set<SensitiveTrace>>();

/** Pipeline stages call this when they allocate request-scoped buffers. */
export function registerSensitiveTrace(
  res: Response,
  trace: SensitiveTrace,
): void {
  const existing = traceRegistry.get(res);
  if (existing !== undefined) {
    existing.add(trace);
    return;
  }
  traceRegistry.set(res, new Set([trace]));
}

/**
 * Scrubs and unregisters every trace for the response. Returns the number
 * of traces scrubbed. Also invoked by the success path on response finish
 * so cleanup is uniform across outcomes.
 */
export function scrubSensitiveTraces(res: Response): number {
  const traces = traceRegistry.get(res);
  if (traces === undefined) {
    return 0;
  }
  let scrubbed = 0;
  for (const trace of traces) {
    try {
      trace.scrub();
      scrubbed += 1;
    } catch {
      // Best-effort by contract; a throwing scrub must not mask the
      // original failure or halt scrubbing of the remaining traces.
    }
  }
  traceRegistry.delete(res);
  return scrubbed;
}

/* -------------------------------------------------------------------------
 * Error classification
 * ---------------------------------------------------------------------- */

interface Classification {
  readonly status: number;
  /** Machine-readable reason code - the ONLY detail the client receives. */
  readonly code: string;
}

function hasHttpStatus(error: unknown): error is { status: number } {
  if (typeof error !== 'object' || error === null) {
    return false;
  }
  const status = (error as { status?: unknown }).status;
  return typeof status === 'number' && status >= 400 && status <= 599;
}

function classify(error: unknown): Classification {
  if (error instanceof PiiScanError || error instanceof InjectionShieldError) {
    // A broken scanner is indistinguishable from an unscanned request:
    // under FAIL_CLOSED that is an upstream-facing outage, not a 4xx.
    return { status: 502, code: 'SECURITY_SUBSYSTEM_FAILURE' };
  }
  if (error instanceof UnresolvedSurrogateError) {
    return { status: 502, code: 'STREAM_RECONSTITUTION_FAILURE' };
  }
  if (error instanceof Error && error.name === 'UpstreamConnectionError') {
    // Matched by name, not instanceof: importing the proxy module here
    // would create a dependency cycle (the proxy registers traces via
    // this module), and the name is a stable part of that error's API.
    return { status: 502, code: 'UPSTREAM_UNREACHABLE' };
  }
  if (hasHttpStatus(error)) {
    // body-parser and friends attach a status; honour 4xx/5xx but still
    // suppress their messages (entity.too.large etc. leak size probes).
    return { status: error.status, code: 'REQUEST_REJECTED' };
  }
  return { status: 500, code: 'GATEWAY_INTERNAL_FAILURE' };
}

/* -------------------------------------------------------------------------
 * Telemetry contract
 * ---------------------------------------------------------------------- */

export interface GatewayErrorEvent {
  readonly requestId: string;
  readonly method: string;
  readonly path: string;
  readonly errorName: string;
  readonly code: string;
  readonly status: number;
  /** 'pre-response' → JSON error sent; 'mid-stream' → socket destroyed. */
  readonly phase: 'pre-response' | 'mid-stream';
  readonly tracesScrubbed: number;
}

export interface ErrorEventSink {
  onGatewayError(event: GatewayErrorEvent): void;
}

/* -------------------------------------------------------------------------
 * The boundary
 * ---------------------------------------------------------------------- */

/**
 * Builds the terminal Express error middleware. Mount LAST. The `next`
 * parameter is required - Express identifies error middleware by arity 4.
 */
export function createErrorHandler(sink?: ErrorEventSink): ErrorRequestHandler {
  return function gatewayErrorBoundary(error, req, res, _next): void {
    // Obligation 1: SCRUB - before any response decision, so no branch
    // below can return with plaintext still staged.
    const tracesScrubbed = scrubSensitiveTraces(res);

    const { status, code } = classify(error);
    const requestIdHeader = res.getHeader('x-request-id');
    const requestId =
      typeof requestIdHeader === 'string' && requestIdHeader.length > 0
        ? requestIdHeader
        : randomUUID();
    const errorName =
      error instanceof Error ? error.name : 'NonErrorThrown';

    if (res.headersSent) {
      // Obligation 2: SEVER. The status line is gone; the only honest
      // signal left is a hard connection teardown. destroy() both the
      // response stream and the underlying socket descriptor - a client
      // must never interpret this stream as complete.
      sink?.onGatewayError({
        requestId,
        method: req.method,
        path: req.path,
        errorName,
        code,
        status,
        phase: 'mid-stream',
        tracesScrubbed,
      });
      res.destroy();
      if (res.socket !== null && !res.socket.destroyed) {
        res.socket.destroy();
      }
      return;
    }

    // Obligation 3: SIGNAL. Generic, reason-coded, nothing else.
    sink?.onGatewayError({
      requestId,
      method: req.method,
      path: req.path,
      errorName,
      code,
      status,
      phase: 'pre-response',
      tracesScrubbed,
    });
    res
      .status(status)
      .set('x-request-id', requestId)
      .json({ error: code, requestId });
  };
}

/* -------------------------------------------------------------------------
 * Process-level guards
 * ---------------------------------------------------------------------- */

/**
 * FAIL_CLOSED extends to the process: an uncaught exception or unhandled
 * rejection means gateway state is unprovable, and an unprovable security
 * gateway must not keep serving. Logs the error class to stderr (never
 * the message - it may embed payload data) and exits non-zero so the
 * supervisor restarts a clean instance.
 *
 * Returns an uninstaller for test harnesses. Installing twice is a no-op.
 */
let processGuardsInstalled = false;

export function installProcessGuards(
  beforeExit?: () => void,
): (() => void) | null {
  if (processGuardsInstalled) {
    return null;
  }
  processGuardsInstalled = true;

  const onFatal = (kind: string) => (cause: unknown): void => {
    const name =
      cause instanceof Error ? cause.name : 'NonErrorThrown';
    process.stderr.write(
      `[valence] FATAL ${kind}: ${name} - fail-closed shutdown.\n`,
    );
    try {
      beforeExit?.();
    } catch {
      // The ship is already sinking; cleanup failures cannot block exit.
    }
    process.exit(1);
  };

  const onUncaught = onFatal('uncaughtException');
  const onUnhandled = onFatal('unhandledRejection');

  process.on('uncaughtException', onUncaught);
  process.on('unhandledRejection', onUnhandled);

  return function uninstallProcessGuards(): void {
    process.removeListener('uncaughtException', onUncaught);
    process.removeListener('unhandledRejection', onUnhandled);
    processGuardsInstalled = false;
  };
}
