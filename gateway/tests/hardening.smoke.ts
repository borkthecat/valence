import assert from 'node:assert/strict';
import { SurrogateCategory, TokenVault } from '../src/core/crypto/tokenVault';
import { HeuristicPiiDetector, PiiScanner } from '../src/core/filters/piiScanner';
import { HeuristicInjectionDetector, InjectionShield, } from '../src/core/filters/injectionShield';
import { SurrogateChunkReconstructor, UnresolvedSurrogateError, } from '../src/core/streaming/chunkReconstructor';
import { createErrorHandler, registerSensitiveTrace, } from '../src/middleware/errorHandler';
import { PiiScanError } from '../src/core/filters/piiScanner';
import type { Request, Response } from 'express';
async function run(): Promise<void> {
    const vault = TokenVault.getInstance();
    const scanner = new PiiScanner(vault, [new HeuristicPiiDetector()]);
    const shield = new InjectionShield([new HeuristicInjectionDetector()]);
    const payloads: Array<[
        string,
        string
    ]> = [
        ['plain', 'a'.repeat(200000)],
        ['email-bait', 'a.b_c%d+e-'.repeat(20000)],
        ['at-flood', ('a'.repeat(50) + '@').repeat(3500)],
        ['key-flood', ('sk-' + 'x'.repeat(19) + ' ').repeat(8000)],
        ['marker-flood', '[M_'.repeat(60000)],
        ['begin-key', '-----BEGIN PRIVATE KEY-----' + 'A'.repeat(190000)],
    ];
    for (const [name, payload] of payloads) {
        const started = process.hrtime.bigint();
        await scanner.scan(payload);
        await shield.evaluate(payload);
        vault.restoreText(payload);
        const ms = Number(process.hrtime.bigint() - started) / 1e6;
        assert.ok(ms < 1000, `ReDoS bound for ${name}: ${ms.toFixed(1)}ms`);
    }
    const tenantA = vault.tokenize('a-secret@tenant-a.com', SurrogateCategory.EMAIL);
    const tenantB = vault.tokenize('b-secret@tenant-b.com', SurrogateCategory.EMAIL);
    const scoped = new SurrogateChunkReconstructor(vault, {
        unresolvedPolicy: 'passthrough',
        allowedSurrogates: new Set([tenantB]),
    });
    const out = scoped.push(`own ${tenantB} foreign ${tenantA} end`) + scoped.flush();
    assert.ok(out.includes('b-secret@tenant-b.com'), 'own surrogate restored');
    assert.ok(!out.includes('a-secret@tenant-a.com'), 'foreign surrogate not restored');
    assert.ok(out.includes(tenantA), 'foreign surrogate left as marker');
    const strict = new SurrogateChunkReconstructor(vault, {
        unresolvedPolicy: 'throw',
        allowedSurrogates: new Set([tenantB]),
    });
    assert.throws(() => strict.push(`foreign ${tenantA}`), UnresolvedSurrogateError, 'out-of-scope surrogate throws under fail-closed');
    const handler = createErrorHandler();
    let scrubbed = 0;
    const preRes = fakeResponse(false);
    registerSensitiveTrace(preRes.res, {
        scrub: () => {
            scrubbed += 1;
        },
    });
    registerSensitiveTrace(preRes.res, {
        scrub: () => {
            throw new Error('scrub boom');
        },
    });
    handler(new PiiScanError(['heuristic-static']), { method: 'POST', path: '/v1/messages' } as unknown as Request, preRes.res, () => undefined);
    assert.equal(preRes.state.status, 502, 'scanner failure maps to 502');
    assert.equal(scrubbed, 1, 'scrub invoked, throwing scrub contained');
    const midRes = fakeResponse(true);
    handler(new UnresolvedSurrogateError('[M_EMAIL_deadbeefdeadbeef]'), { method: 'POST', path: '/v1/messages' } as unknown as Request, midRes.res, () => undefined);
    assert.equal(midRes.state.destroyed, true, 'mid-stream failure destroys response');
    assert.equal(midRes.state.socketDestroyed, true, 'mid-stream failure destroys socket');
    TokenVault.resetInstance();
    console.log('hardening.smoke: OK');
}
function fakeResponse(headersSent: boolean): {
    res: Response;
    state: {
        status: number;
        destroyed: boolean;
        socketDestroyed: boolean;
    };
} {
    const state = { status: 0, destroyed: false, socketDestroyed: false };
    const res = {
        headersSent,
        getHeader: () => undefined,
        status(code: number) {
            state.status = code;
            return this;
        },
        set() {
            return this;
        },
        json() {
            return this;
        },
        destroy() {
            state.destroyed = true;
        },
        socket: {
            destroyed: false,
            destroy() {
                state.socketDestroyed = true;
            },
        },
    } as unknown as Response;
    return { res, state };
}
run().catch((error) => {
    console.error('hardening.smoke: FAILED', error);
    process.exit(1);
});
