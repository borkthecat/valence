import { createHmac, timingSafeEqual } from 'node:crypto';
import type { NextFunction, Request, RequestHandler, Response } from 'express';
import type { AuthenticatedRequest } from './types';

export interface JwtClaims {
  readonly sub?: string;
  readonly tenant?: string;
  readonly scope?: string;
  readonly scopes?: readonly string[];
  readonly exp?: number;
  readonly nbf?: number;
  readonly iss?: string;
  readonly aud?: string | readonly string[];
  readonly jti?: string;
}

export class JwtError extends Error {
  public constructor(
    message: string,
    public readonly code:
      | 'malformed'
      | 'unsupported_alg'
      | 'bad_signature'
      | 'expired'
      | 'not_yet_valid'
      | 'issuer_mismatch'
      | 'audience_mismatch'
      | 'missing_tenant',
  ) {
    super(message);
    this.name = 'JwtError';
  }
}

const MAX_JWT_LENGTH = 4096;

function base64UrlDecode(segment: string): Buffer {
  if (!/^[A-Za-z0-9_-]*$/.test(segment)) {
    throw new JwtError('invalid base64url segment', 'malformed');
  }
  const normalized = segment.replace(/-/g, '+').replace(/_/g, '/');
  const padLength = normalized.length % 4 === 0 ? 0 : 4 - (normalized.length % 4);
  return Buffer.from(normalized + '='.repeat(padLength), 'base64');
}

export interface VerifyJwtOptions {
  readonly issuer?: string;
  readonly audience?: string;
  readonly now?: number;
}

export function verifyJwt(
  token: string,
  secret: string,
  options: VerifyJwtOptions = {},
): JwtClaims {
  if (token.length > MAX_JWT_LENGTH) {
    throw new JwtError('token too large', 'malformed');
  }
  const parts = token.split('.');
  if (parts.length !== 3) {
    throw new JwtError('token must have three segments', 'malformed');
  }
  const [headerB64, payloadB64, signatureB64] = parts as [string, string, string];

  let header: { alg?: unknown; typ?: unknown };
  try {
    header = JSON.parse(base64UrlDecode(headerB64).toString('utf8'));
  } catch {
    throw new JwtError('unreadable header', 'malformed');
  }
  if (header.alg !== 'HS256') {
    throw new JwtError('only HS256 is supported', 'unsupported_alg');
  }

  const expected = createHmac('sha256', secret)
    .update(`${headerB64}.${payloadB64}`)
    .digest();
  const provided = base64UrlDecode(signatureB64);
  if (
    expected.length !== provided.length ||
    !timingSafeEqual(expected, provided)
  ) {
    throw new JwtError('signature verification failed', 'bad_signature');
  }

  let claims: JwtClaims;
  try {
    claims = JSON.parse(base64UrlDecode(payloadB64).toString('utf8'));
  } catch {
    throw new JwtError('unreadable payload', 'malformed');
  }

  const now = options.now ?? Math.floor(Date.now() / 1000);
  if (typeof claims.exp === 'number' && now >= claims.exp) {
    throw new JwtError('token expired', 'expired');
  }
  if (typeof claims.nbf === 'number' && now < claims.nbf) {
    throw new JwtError('token not yet valid', 'not_yet_valid');
  }
  if (options.issuer !== undefined && claims.iss !== options.issuer) {
    throw new JwtError('issuer mismatch', 'issuer_mismatch');
  }
  if (options.audience !== undefined) {
    const audiences = Array.isArray(claims.aud)
      ? claims.aud
      : claims.aud === undefined
        ? []
        : [claims.aud];
    if (!audiences.includes(options.audience)) {
      throw new JwtError('audience mismatch', 'audience_mismatch');
    }
  }
  if (typeof claims.tenant !== 'string' && typeof claims.sub !== 'string') {
    throw new JwtError('tenant or subject is required', 'missing_tenant');
  }
  return claims;
}

export function extractScopes(claims: JwtClaims): string[] {
  const fromString = typeof claims.scope === 'string' ? claims.scope.split(/\s+/) : [];
  const fromArray = Array.isArray(claims.scopes) ? [...claims.scopes] : [];
  return [...new Set([...fromString, ...fromArray].filter((s) => s.length > 0))];
}

export interface JwtAuthConfig {
  readonly secret: string;
  readonly requiredScope: string;
  readonly issuer?: string;
  readonly audience?: string;
}

export interface JwtAuthEventSink {
  onRejected(context: {
    readonly reason: 'missing' | 'invalid' | 'forbidden';
    readonly method: string;
    readonly path: string;
  }): void;
}

function bearerToken(req: Request): string | null {
  const authorization = req.headers.authorization;
  if (typeof authorization !== 'string') {
    return null;
  }
  const [scheme, ...rest] = authorization.split(' ');
  if (scheme === undefined || scheme.toLowerCase() !== 'bearer' || rest.length !== 1) {
    return null;
  }
  const token = rest[0];
  return token !== undefined && token.length > 0 ? token : null;
}

export function createJwtAuth(
  config: JwtAuthConfig,
  eventSink?: JwtAuthEventSink,
): RequestHandler {
  if (config.secret.length < 32) {
    throw new RangeError('createJwtAuth: secret must be at least 32 characters');
  }

  return function jwtAuth(
    req: AuthenticatedRequest,
    res: Response,
    next: NextFunction,
  ): void {
    const token = bearerToken(req);
    if (token === null) {
      eventSink?.onRejected({ reason: 'missing', method: req.method, path: req.path });
      res.status(401).set('WWW-Authenticate', 'Bearer realm="valence"').json({ error: 'unauthorized' });
      return;
    }

    let claims: JwtClaims;
    try {
      const options: VerifyJwtOptions = {};
      Object.assign(
        options,
        config.issuer === undefined ? {} : { issuer: config.issuer },
        config.audience === undefined ? {} : { audience: config.audience },
      );
      claims = verifyJwt(token, config.secret, options);
    } catch {
      eventSink?.onRejected({ reason: 'invalid', method: req.method, path: req.path });
      res.status(401).json({ error: 'unauthorized' });
      return;
    }

    const scopes = extractScopes(claims);
    if (!scopes.includes(config.requiredScope)) {
      eventSink?.onRejected({ reason: 'forbidden', method: req.method, path: req.path });
      res.status(403).json({ error: 'forbidden' });
      return;
    }

    const tenantId = claims.tenant ?? claims.sub;
    if (tenantId === undefined) {
      eventSink?.onRejected({ reason: 'invalid', method: req.method, path: req.path });
      res.status(401).json({ error: 'unauthorized' });
      return;
    }
    req.valence = { tenantId, scopes };
    next();
  };
}
