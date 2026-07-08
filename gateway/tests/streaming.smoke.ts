import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { SurrogateCategory, TokenVault } from '../src/core/crypto/tokenVault';
import { SurrogateChunkReconstructor, createReconstitutionStream, UnresolvedSurrogateError, } from '../src/core/streaming/chunkReconstructor';
async function run(): Promise<void> {
    const vault = TokenVault.getInstance();
    const surrogate = await vault.tokenize('alice@example.com', SurrogateCategory.EMAIL);
    const full = `Reply sent to ${surrogate} just now.`;
    const expected = 'Reply sent to alice@example.com just now.';
    for (const splitAt of [16, 20, 25, 30]) {
        const r = new SurrogateChunkReconstructor(vault);
        const out = await r.push(full.slice(0, splitAt)) + await r.push(full.slice(splitAt)) + await r.flush();
        assert.equal(out, expected, `string split at ${splitAt}`);
    }
    const bytes = Buffer.from(`héllo ${surrogate} wörld`, 'utf8');
    for (const cut of [2, 9, 18, bytes.length - 3]) {
        const r = new SurrogateChunkReconstructor(vault);
        const out = await r.push(bytes.subarray(0, cut)) + await r.push(bytes.subarray(cut)) + await r.flush();
        assert.equal(out, 'héllo alice@example.com wörld', `byte split at ${cut}`);
    }
    {
        const r = new SurrogateChunkReconstructor(vault);
        let out = '';
        for (const b of bytes)
            out += await r.push(Buffer.from([b]));
        out += await r.flush();
        assert.equal(out, 'héllo alice@example.com wörld', 'one byte at a time');
    }
    {
        const r = new SurrogateChunkReconstructor(vault);
        const out = await r.push('array[M_INDEX] and [M_ over-long ') + await r.flush();
        assert.equal(out, 'array[M_INDEX] and [M_ over-long ', 'lookalike passthrough');
    }
    {
        const r = new SurrogateChunkReconstructor(vault, { unresolvedPolicy: 'throw' });
        await assert.rejects(() => r.push('x [M_EMAIL_deadbeefdeadbeef] y'), UnresolvedSurrogateError, 'unknown surrogate throws under throw policy');
    }
    {
        const r = new SurrogateChunkReconstructor(vault, { unresolvedPolicy: 'redact' });
        const out = await r.push('x [M_EMAIL_deadbeefdeadbeef] y') + await r.flush();
        assert.equal(out, 'x [REDACTED] y', 'redact policy');
    }
    {
        const r = new SurrogateChunkReconstructor(vault);
        const source = Readable.from([
            Buffer.from(`data: {"text":"mail ${surrogate.slice(0, 9)}`),
            Buffer.from(`${surrogate.slice(9)} done"}\n\n`),
        ]);
        const chunks: Buffer[] = [];
        for await (const c of source.pipe(createReconstitutionStream(r))) {
            chunks.push(Buffer.from(c as Buffer));
        }
        assert.equal(Buffer.concat(chunks).toString('utf8'), 'data: {"text":"mail alice@example.com done"}\n\n', 'transform pipeline restores across chunks');
    }
    {
        const r = new SurrogateChunkReconstructor(vault);
        await r.push('secret ');
        r.scrub();
        await assert.rejects(() => r.push('more'), 'scrub blocks reuse');
    }
    TokenVault.resetInstance();
    console.log('streaming.smoke: OK');
}
run().catch((error) => {
    console.error('streaming.smoke: FAILED', error);
    process.exit(1);
});
