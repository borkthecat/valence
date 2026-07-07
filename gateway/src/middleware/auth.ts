/**
 * Valence Gateway - Zero-Trust Gateway Authentication Middleware
 *
 * Verifies the client-presented gateway credential before any request may
 * touch the scanning pipeline or the upstream proxy.
 *
 * Timing side-channel posture:
 *  - Both sides of the comparison are first digested with SHA-256, so the
 *    buffers handed to `crypto.timingSafeEqual` always have equal length.
 *    Comparison time is therefore independent of both the length and the
 *    content of the presented credential.
 *  - Missing-credential and wrong-credential paths return byte-identical
 *    401 responses; the response body never distinguishes the failure
 *    reason, and the credential itself is never logged or echoed.
 *
 * The middleware is a factory (`createGatewayAuth`) rather than a module
 * singleton so that (a) tests can construct it with arbitrary keys without
 * booting the full environment, and (b) the composition root remains the
 * single place that touches validated configuration.
 */

import { createHash, timingSafeEqual } from 'node:crypto';
import type { NextFunction, Request, RequestHandler, Response } from 'express';

/** Canonical header for machine clients; Bearer scheme is also accepted. */
export const GATEWAY_KEY_HEADER = 'x-valence-key';

/**
 * Upper bound on accepted credential length. SHA-256 makes comparison
 * cost length-independent, but hashing itself is O(n) - without a cap, a
 * multi-megabyte Authorization header becomes a cheap CPU-burn primitive.
 */
const MAX_CREDENTIAL_LENGTH = 512;

/** Optional hook for structured security telemetry (no credential data). */
export interface AuthEventSink {
  onRejected(context: {
    readonly reason: 'missing' | 'invalid' | 'oversized';
    readonly method: string;
    readonly path: string;
    readonly remoteAddress: string | undefined;
  }): void;
}

function sha256(value: string): Buffer {
  return createHash('sha256').update(value, 'utf8').digest();
}

/**
 * Extracts the presented credential, preferring the dedicated gateway
 * header over the Authorization Bearer scheme. Returns null when absent
 * or structurally unusable; the caller maps every null to the same 401.
 */
function extractCredential(req: Request): string | null {
  const headerValue = req.headers[GATEWAY_KEY_HEADER];
  if (typeof headerValue === 'string' && headerValue.length > 0) {
    return headerValue;
  }
  // Express lowercases header names; repeated headers arrive as arrays.
  // A repeated credential header is anomalous - treat as absent rather
  // than guessing which copy the client meant.
  if (Array.isArray(headerValue)) {
    return null;
  }

  const authorization = req.headers.authorization;
  if (typeof authorization !== 'string') {
    return null;
  }
  const [scheme, ...rest] = authorization.split(' ');
  if (
    scheme === undefined ||
    scheme.toLowerCase() !== 'bearer' ||
    rest.length !== 1
  ) {
    return null;
  }
  const token = rest[0];
  return token !== undefined && token.length > 0 ? token : null;
}

function rejectUnauthorized(res: Response): void {
  res
    .status(401)
    .set('WWW-Authenticate', 'Bearer realm="valence"')
    // Deliberately generic: identical body for missing, malformed,
    // oversized, and wrong credentials - no oracle for enumeration.
    .json({ error: 'unauthorized' });
}

/**
 * Builds the authentication middleware bound to one expected gateway key.
 *
 * @param expectedKey Validated GATEWAY_API_KEY from the environment module.
 * @param eventSink   Optional telemetry hook; receives rejection metadata
 *                    only - never any part of a credential.
 */
export function createGatewayAuth(
  expectedKey: string,
  eventSink?: AuthEventSink,
): RequestHandler {
  if (expectedKey.length < 32) {
    // Mirrors the Zod floor in environment.ts; enforced again here so the
    // middleware is safe even if constructed outside the composition root.
    throw new RangeError(
      'createGatewayAuth: expectedKey must be at least 32 characters',
    );
  }

  // Digest precomputed once; per-request work is one hash of the
  // presented value plus one constant-time buffer comparison.
  const expectedDigest = sha256(expectedKey);

  return function gatewayAuth(
    req: Request,
    res: Response,
    next: NextFunction,
  ): void {
    const credential = extractCredential(req);

    if (credential === null) {
      eventSink?.onRejected({
        reason: 'missing',
        method: req.method,
        path: req.path,
        remoteAddress: req.socket.remoteAddress,
      });
      rejectUnauthorized(res);
      return;
    }

    if (credential.length > MAX_CREDENTIAL_LENGTH) {
      eventSink?.onRejected({
        reason: 'oversized',
        method: req.method,
        path: req.path,
        remoteAddress: req.socket.remoteAddress,
      });
      rejectUnauthorized(res);
      return;
    }

    const presentedDigest = sha256(credential);
    // Equal-length SHA-256 digests: timingSafeEqual never throws here and
    // runs in time independent of where the buffers differ.
    const authorized = timingSafeEqual(presentedDigest, expectedDigest);

    if (!authorized) {
      eventSink?.onRejected({
        reason: 'invalid',
        method: req.method,
        path: req.path,
        remoteAddress: req.socket.remoteAddress,
      });
      rejectUnauthorized(res);
      return;
    }

    next();
  };
}
