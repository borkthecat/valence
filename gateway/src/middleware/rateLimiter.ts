import type { NextFunction, RequestHandler, Response } from 'express';
import type { AuthenticatedRequest } from './types';

interface Bucket {
  count: number;
  resetAt: number;
}

export interface RateLimitConfig {
  readonly maxRequests: number;
  readonly windowMs: number;
  readonly now?: () => number;
}

export interface RateLimitEventSink {
  onRateLimited(context: {
    readonly tenantId: string;
    readonly method: string;
    readonly path: string;
    readonly retryAfterSeconds: number;
  }): void;
}

export function createTenantRateLimiter(
  config: RateLimitConfig,
  sink?: RateLimitEventSink,
): RequestHandler {
  if (config.maxRequests < 1 || config.windowMs < 1000) {
    throw new RangeError('rate limiter requires a positive limit and window >= 1000ms');
  }

  const now = config.now ?? Date.now;
  const buckets = new Map<string, Bucket>();

  return function tenantRateLimiter(
    req: AuthenticatedRequest,
    res: Response,
    next: NextFunction,
  ): void {
    const tenantId = req.valence?.tenantId ?? 'unidentified';
    const current = now();
    let bucket = buckets.get(tenantId);

    if (bucket === undefined || current >= bucket.resetAt) {
      bucket = { count: 0, resetAt: current + config.windowMs };
      buckets.set(tenantId, bucket);
    }

    bucket.count += 1;
    if (bucket.count <= config.maxRequests) {
      next();
      return;
    }

    const retryAfterSeconds = Math.max(1, Math.ceil((bucket.resetAt - current) / 1000));
    sink?.onRateLimited({
      tenantId,
      method: req.method,
      path: req.path,
      retryAfterSeconds,
    });
    res
      .status(429)
      .set('Retry-After', String(retryAfterSeconds))
      .json({ error: 'rate_limited' });

    if (buckets.size > config.maxRequests * 4) {
      for (const [key, stale] of buckets) {
        if (current >= stale.resetAt) {
          buckets.delete(key);
        }
      }
    }
  };
}
