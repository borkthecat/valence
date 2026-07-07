import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { NextFunction, Response } from 'express';
import { createJwtAuth, verifyJwt } from '../src/middleware/jwtAuth';
import { createTenantRateLimiter } from '../src/middleware/rateLimiter';
import type { AuthenticatedRequest } from '../src/middleware/types';
import { MetricsRegistry } from '../src/observability/metrics';
import { HashChainedAuditLog } from '../src/observability/auditLog';

const SECRET = 'jwt-secret-0123456789abcdef0123456789abcdef';

function b64url(value: unknown): string {
  return Buffer.from(JSON.stringify(value))
    .toString('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
}

function sign(payload: Record<string, unknown>): string {
  const header = b64url({ alg: 'HS256', typ: 'JWT' });
  const body = b64url(payload);
  const signature = createHmac('sha256', SECRET)
    .update(`${header}.${body}`)
    .digest('base64')
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_');
  return `${header}.${body}.${signature}`;
}

function fakeResponse(): { res: Response; state: { status: number; body: unknown } } {
  const state = { status: 0, body: undefined as unknown };
  const res = {
    status(code: number) {
      state.status = code;
      return this;
    },
    set() {
      return this;
    },
    json(body: unknown) {
      state.body = body;
      return this;
    },
  } as unknown as Response;
  return { res, state };
}

async function run(): Promise<void> {
  const token = sign({
    tenant: 'tenant-a',
    scope: 'valence:proxy profile:read',
    exp: Math.floor(Date.now() / 1000) + 60,
  });
  const claims = verifyJwt(token, SECRET);
  assert.equal(claims.tenant, 'tenant-a');

  const auth = createJwtAuth({ secret: SECRET, requiredScope: 'valence:proxy' });
  const req = {
    method: 'POST',
    path: '/v1/messages',
    headers: { authorization: `Bearer ${token}` },
  } as unknown as AuthenticatedRequest;
  const { res, state } = fakeResponse();
  let nextCalled = false;
  auth(req, res, (() => {
    nextCalled = true;
  }) as NextFunction);
  assert.equal(nextCalled, true);
  assert.equal(req.valence?.tenantId, 'tenant-a');
  assert.equal(state.status, 0);

  const denied = fakeResponse();
  createJwtAuth({ secret: SECRET, requiredScope: 'admin:write' })(
    req,
    denied.res,
    (() => undefined) as NextFunction,
  );
  assert.equal(denied.state.status, 403);

  let now = 1_000;
  const limiter = createTenantRateLimiter({
    maxRequests: 2,
    windowMs: 1_000,
    now: () => now,
  });
  for (let i = 0; i < 2; i += 1) {
    const ok = fakeResponse();
    limiter(req, ok.res, (() => undefined) as NextFunction);
    assert.equal(ok.state.status, 0);
  }
  const blocked = fakeResponse();
  limiter(req, blocked.res, (() => undefined) as NextFunction);
  assert.equal(blocked.state.status, 429);
  now = 2_001;
  const reset = fakeResponse();
  limiter(req, reset.res, (() => undefined) as NextFunction);
  assert.equal(reset.state.status, 0);

  const registry = new MetricsRegistry();
  registry.counter('valence_test_total', 'test counter').inc({ tenant: 'tenant-a' }, 3);
  const rendered = registry.render();
  assert.match(rendered, /# TYPE valence_test_total counter/);
  assert.match(rendered, /valence_test_total\{tenant="tenant-a"\} 3/);

  const temp = mkdtempSync(join(tmpdir(), 'valence-audit-'));
  try {
    const path = join(temp, 'audit.log');
    const audit = new HashChainedAuditLog(path);
    audit.record({ type: 'auth_rejected', reason: 'invalid' });
    audit.record({ type: 'request_forwarded', upstream_status: 200 });
    await audit.flush();
    const records = readFileSync(path, 'utf8').trim().split(/\r?\n/).map((line) => JSON.parse(line));
    assert.equal(records.length, 2);
    assert.equal(records[1].previous_hash, records[0].hash);
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }

  console.log('enterprise.smoke: OK');
}

run().catch((error) => {
  console.error('enterprise.smoke: FAILED', error);
  process.exit(1);
});
