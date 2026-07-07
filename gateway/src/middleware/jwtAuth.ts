import { createHmac, createPublicKey, createVerify, timingSafeEqual } from 'node:crypto';
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
      | 'missing_tenant'
      | 'invalid_claims',
  ) {
    super(message);
    this.name = 'JwtError';
  }
}

const MAX_JWT_LENGTH = 4096;
const MAX_TENANT_LENGTH = 128;
export type JwtAlgorithm = 'HS256' | 'RS256';

type JwtHeader = {
  readonly alg?: unknown;
  readonly typ?: unknown;
  readonly kid?: unknown;
};

function base64UrlDecode(segment: string): Buffer {
  if (!/^[A-Za-z0-9_-]*$/.test(segment)) {
    throw new JwtError('invalid base64url segment', 'malformed');
  }
  const normalized = segment.replace(/-/g, '+').replace(/_/g, '/');
  const padLength = normalized.length % 4 === 0 ? 0 : 4 - (normalized.length % 4);
  return Buffer.from(normalized + '='.repeat(padLength), 'base64');
}

export interface VerifyJwtOptions {
  readonly algorithm?: JwtAlgorithm;
  readonly secret?: string;
  readonly publicKeyPem?: string;
  readonly issuer?: string;
  readonly audience?: string;
  readonly now?: number;
  readonly clockSkewSeconds?: number;
}

function parseObject(segment: string, label: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(base64UrlDecode(segment).toString('utf8'));
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new JwtError(`${label} must be a JSON object`, 'malformed');
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof JwtError) {
      throw error;
    }
    throw new JwtError(`unreadable ${label}`, 'malformed');
  }
}

function verifySignature(
  signingInput: string,
  signatureB64: string,
  header: JwtHeader,
  options: VerifyJwtOptions,
): void {
  const algorithm = options.algorithm ?? 'HS256';
  if (header.alg !== algorithm) {
    throw new JwtError(`only ${algorithm} is supported`, 'unsupported_alg');
  }

  const provided = base64UrlDecode(signatureB64);
  if (algorithm === 'HS256') {
    if (options.secret === undefined) {
      throw new JwtError('HS256 secret is not configured', 'bad_signature');
    }
    const expected = createHmac('sha256', options.secret).update(signingInput).digest();
    if (expected.length !== provided.length || !timingSafeEqual(expected, provided)) {
      throw new JwtError('signature verification failed', 'bad_signature');
    }
    return;
  }

  if (options.publicKeyPem === undefined) {
    throw new JwtError('RS256 public key is not configured', 'bad_signature');
  }
  let valid = false;
  try {
    const verifier = createVerify('RSA-SHA256');
    verifier.update(signingInput);
    verifier.end();
    valid = verifier.verify(createPublicKey(options.publicKeyPem), provided);
  } catch {
    throw new JwtError('signature verification failed', 'bad_signature');
  }
  if (!valid) {
    throw new JwtError('signature verification failed', 'bad_signature');
  }
}

function assertClaimsShape(claims: JwtClaims): void {
  const tenant = claims.tenant ?? claims.sub;
  if (typeof tenant !== 'string' || tenant.length === 0 || tenant.length > MAX_TENANT_LENGTH) {
    throw new JwtError('tenant or subject is required', 'missing_tenant');
  }
  if (claims.scope !== undefined && typeof claims.scope !== 'string') {
    throw new JwtError('scope must be a string', 'invalid_claims');
  }
  if (
    claims.scopes !== undefined &&
    (!Array.isArray(claims.scopes) || claims.scopes.some((scope) => typeof scope !== 'string'))
  ) {
    throw new JwtError('scopes must be a string array', 'invalid_claims');
  }
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

  const header = parseObject(headerB64, 'header') as JwtHeader;
  const verifyOptions: VerifyJwtOptions = {
    ...options,
    secret: options.secret ?? secret,
  };
  verifySignature(`${headerB64}.${payloadB64}`, signatureB64, header, verifyOptions);

  const claims = parseObject(payloadB64, 'payload') as JwtClaims;

  const now = options.now ?? Math.floor(Date.now() / 1000);
  const skew = options.clockSkewSeconds ?? 0;
  if (claims.exp !== undefined && typeof claims.exp !== 'number') {
    throw new JwtError('exp must be numeric', 'invalid_claims');
  }
  if (claims.nbf !== undefined && typeof claims.nbf !== 'number') {
    throw new JwtError('nbf must be numeric', 'invalid_claims');
  }
  if (typeof claims.exp === 'number' && now - skew >= claims.exp) {
    throw new JwtError('token expired', 'expired');
  }
  if (typeof claims.nbf === 'number' && now + skew < claims.nbf) {
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
  assertClaimsShape(claims);
  return claims;
}

export function extractScopes(claims: JwtClaims): string[] {
  const fromString = typeof claims.scope === 'string' ? claims.scope.split(/\s+/) : [];
  const fromArray = Array.isArray(claims.scopes) ? [...claims.scopes] : [];
  return [...new Set([...fromString, ...fromArray].filter((s) => s.length > 0))];
}

export interface JwtAuthConfig {
  readonly algorithm?: JwtAlgorithm;
  readonly secret?: string;
  readonly publicKeyPem?: string;
  readonly requiredScope: string;
  readonly issuer?: string;
  readonly audience?: string;
  readonly clockSkewSeconds?: number;
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
  const algorithm = config.algorithm ?? 'HS256';
  if (algorithm === 'HS256' && (config.secret === undefined || config.secret.length < 32)) {
    throw new RangeError('createJwtAuth: secret must be at least 32 characters');
  }
  if (algorithm === 'RS256' && config.publicKeyPem === undefined) {
    throw new RangeError('createJwtAuth: publicKeyPem is required for RS256');
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
        { algorithm },
        config.secret === undefined ? {} : { secret: config.secret },
        config.publicKeyPem === undefined ? {} : { publicKeyPem: config.publicKeyPem },
        config.issuer === undefined ? {} : { issuer: config.issuer },
        config.audience === undefined ? {} : { audience: config.audience },
        config.clockSkewSeconds === undefined
          ? {}
          : { clockSkewSeconds: config.clockSkewSeconds },
      );
      claims = verifyJwt(token, '', options);
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
