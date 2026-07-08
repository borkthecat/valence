import assert from 'node:assert/strict';
import { createHmac, createSign, generateKeyPairSync } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { NextFunction, Response } from 'express';
import { createJwtAuth, verifyJwt } from '../src/middleware/jwtAuth';
import { createTenantRateLimiter } from '../src/middleware/rateLimiter';
import type { AuthenticatedRequest } from '../src/middleware/types';
import { MetricsRegistry } from '../src/observability/metrics';
import { HashChainedAuditLog, verifyAuditLog } from '../src/observability/auditLog';
import { FileSecretsProvider } from '../src/config/secrets';
import { parseIngestionPayload } from '../src/routes/ingestSchema';
import { buildQueuedMessages } from '../src/services/queueEnvelope';
import { validateEvidenceUrls } from '../src/services/evidenceUrlValidator';
const SECRET = 'jwt-secret-0123456789abcdef0123456789abcdef';
function b64url(value: unknown): string {
    return Buffer.from(JSON.stringify(value))
        .toString('base64')
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
}
function signHs256(payload: Record<string, unknown>): string {
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
function signRs256(payload: Record<string, unknown>, privateKeyPem: string): string {
    const header = b64url({ alg: 'RS256', typ: 'JWT', kid: 'local-test-key' });
    const body = b64url(payload);
    const signer = createSign('RSA-SHA256');
    signer.update(`${header}.${body}`);
    signer.end();
    const signature = signer.sign(privateKeyPem, 'base64url');
    return `${header}.${body}.${signature}`;
}
function fakeResponse(): {
    res: Response;
    state: {
        status: number;
        body: unknown;
    };
} {
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
    const token = signHs256({
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
    createJwtAuth({ secret: SECRET, requiredScope: 'admin:write' })(req, denied.res, (() => undefined) as NextFunction);
    assert.equal(denied.state.status, 403);
    const pair = generateKeyPairSync('rsa', {
        modulusLength: 2048,
        publicKeyEncoding: { type: 'spki', format: 'pem' },
        privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    });
    const rsToken = signRs256({
        sub: 'tenant-rs',
        scopes: ['valence:proxy'],
        exp: Math.floor(Date.now() / 1000) + 60,
    }, pair.privateKey);
    const rsClaims = verifyJwt(rsToken, '', {
        algorithm: 'RS256',
        publicKeyPem: pair.publicKey,
    });
    assert.equal(rsClaims.sub, 'tenant-rs');
    const parsedIngest = parseIngestionPayload({
        batch_id: 'batch-1',
        tenant_id: 'tenant-a',
        profiles: [
            {
                candidate_id: 'candidate-1',
                entity_type: 'product',
                title: 'Verified product candidate',
                description: 'Enterprise product evidence with seller signals and image hashes.',
                age: 34,
                retail_channel: 'direct',
                era: '2020s',
                colorway: 'midnight-sapphire',
                anniversary: true,
                raw_score: 91.5,
                attributes: {
                    brand: 'Arai',
                    condition: 'new',
                },
                signals: {
                    seller_trust: 0.98,
                    price_deviation: 0.04,
                },
                images: [
                    {
                        url: 'https://cdn.example.test/product.webp',
                        sha256: 'a'.repeat(64),
                        mime_type: 'image/webp',
                        source: 'seller-upload',
                        view: 'front',
                        perceptual_hash: '0123456789abcdef',
                        quality_score: 0.93,
                    },
                    {
                        url: 'https://cdn.example.test/product-back.webp',
                        sha256: 'b'.repeat(64),
                        mime_type: 'image/webp',
                        source: 'seller-upload',
                        view: 'back',
                    },
                ],
                links: [{
                    url: 'https://catalog.example.test/product-1',
                    source: 'manufacturer-catalog',
                    media_type: 'text/html',
                }],
            },
        ],
    });
    assert.equal(parsedIngest.profiles.length, 1);
    assert.equal(parsedIngest.profiles[0]?.images?.length, 2);
    assert.equal(parsedIngest.profiles[0]?.links?.length, 1);
    assert.equal(parsedIngest.profiles[0]?.anniversary, true);
    const queued = buildQueuedMessages('tenant-a', 'batch-1', parsedIngest.profiles);
    const envelope = JSON.parse(queued[0]?.value ?? '{}') as Record<string, unknown>;
    assert.equal(queued[0]?.key, `tenant-a:batch-1:${String(envelope.batch_fingerprint)}`);
    assert.match(String(envelope.message_id), /^[a-f0-9]{64}$/);
    assert.equal(envelope.batch_size, 1);
    assert.equal(envelope.profile_index, 0);
    const checkedUrls = await validateEvidenceUrls(parsedIngest.profiles, {
        maxUrls: 10,
        timeoutMs: 1000,
        resolve: async () => ['93.184.216.34'],
        request: async (input, init) => {
            const url = String(input);
            const type = url.includes('catalog') ? 'text/html' : 'image/webp';
            assert.equal(init?.method, 'HEAD');
            assert.equal(init?.redirect, 'error');
            return new globalThis.Response(null, { status: 200, headers: { 'content-type': type } });
        },
    });
    assert.equal(checkedUrls, 3);
    await assert.rejects(() => validateEvidenceUrls(parsedIngest.profiles, {
        maxUrls: 10,
        timeoutMs: 1000,
        resolve: async () => ['127.0.0.1'],
    }));
    assert.throws(() => parseIngestionPayload({
        batch_id: 'batch-score',
        tenant_id: 'tenant-a',
        profiles: [{
            candidate_id: 'candidate-score',
            age: 34,
            retail_channel: 'direct',
            era: '2020s',
            raw_score: 101,
        }],
    }));
    assert.throws(() => parseIngestionPayload({
        batch_id: 'batch-duplicate',
        tenant_id: 'tenant-a',
        profiles: [
            { candidate_id: 'same', age: 1, retail_channel: 'direct', era: '2025', raw_score: 50 },
            { candidate_id: 'same', age: 2, retail_channel: 'direct', era: '2025', raw_score: 60 },
        ],
    }));
    assert.throws(() => parseIngestionPayload({
        batch_id: 'batch-1',
        tenant_id: 'tenant-a',
        profiles: [
            {
                candidate_id: 'candidate-2',
                age: 34,
                retail_channel: 'direct',
                era: '2020s',
                raw_score: 91.5,
                images: [
                    {
                        url: 'http://cdn.example.test/product.webp',
                        sha256: 'a'.repeat(64),
                        mime_type: 'image/webp',
                        source: 'seller-upload',
                    },
                ],
            },
        ],
    }));
    assert.throws(() => parseIngestionPayload({
        batch_id: 'batch-1',
        tenant_id: 'tenant-a',
        profiles: [],
    }));
    let now = 1000;
    const limiter = createTenantRateLimiter({
        maxRequests: 2,
        windowMs: 1000,
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
    now = 2001;
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
        assert.deepEqual(verifyAuditLog(path), { valid: true, records: 2 });
        records[0].event.reason = 'tampered';
        writeFileSync(path, `${records.map((record) => JSON.stringify(record)).join('\n')}\n`);
        const tampered = verifyAuditLog(path);
        assert.equal(tampered.valid, false);
        assert.equal(tampered.error, 'hash mismatch');
        const secretsPath = join(temp, 'secrets.json');
        writeFileSync(secretsPath, JSON.stringify({
            UPSTREAM_API_KEY: 'sk-provider-0123456789',
            GATEWAY_API_KEY: 'gateway-key-0123456789abcdef0123456789abcdef',
            JWT_PUBLIC_KEY_PEM: pair.publicKey,
        }));
        const secrets = new FileSecretsProvider(secretsPath).loadGatewaySecrets();
        assert.equal(secrets.upstreamApiKey, 'sk-provider-0123456789');
        assert.equal(secrets.jwtPublicKeyPem, pair.publicKey);
    }
    finally {
        rmSync(temp, { recursive: true, force: true });
    }
    console.log('enterprise.smoke: OK');
}
run().catch((error) => {
    console.error('enterprise.smoke: FAILED', error);
    process.exit(1);
});
