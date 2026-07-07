/**
 * Streaming surrogate reconstitution: chunk-boundary and byte-boundary
 * splits, lookalike passthrough, unresolved policies, and scrub.
 */

import assert from 'node:assert/strict';
import { Readable } from 'node:stream';
import { SurrogateCategory, TokenVault } from '../src/core/crypto/tokenVault';
import {
  SurrogateChunkReconstructor,
  createReconstitutionStream,
  UnresolvedSurrogateError,
} from '../src/core/streaming/chunkReconstructor';

async function run(): Promise<void> {
  const vault = TokenVault.getInstance();
  const surrogate = vault.tokenize('alice@example.com', SurrogateCategory.EMAIL);
  const full = `Reply sent to ${surrogate} just now.`;
  const expected = 'Reply sent to alice@example.com just now.';

  for (const splitAt of [16, 20, 25, 30]) {
    const r = new SurrogateChunkReconstructor(vault);
    const out = r.push(full.slice(0, splitAt)) + r.push(full.slice(splitAt)) + r.flush();
    assert.equal(out, expected, `string split at ${splitAt}`);
  }

  const bytes = Buffer.from(`héllo ${surrogate} wörld`, 'utf8');
  for (const cut of [2, 9, 18, bytes.length - 3]) {
    const r = new SurrogateChunkReconstructor(vault);
    const out = r.push(bytes.subarray(0, cut)) + r.push(bytes.subarray(cut)) + r.flush();
    assert.equal(out, 'héllo alice@example.com wörld', `byte split at ${cut}`);
  }

  {
    const r = new SurrogateChunkReconstructor(vault);
    let out = '';
    for (const b of bytes) out += r.push(Buffer.from([b]));
    out += r.flush();
    assert.equal(out, 'héllo alice@example.com wörld', 'one byte at a time');
  }

  {
    const r = new SurrogateChunkReconstructor(vault);
    const out = r.push('array[M_INDEX] and [M_ over-long ') + r.flush();
    assert.equal(out, 'array[M_INDEX] and [M_ over-long ', 'lookalike passthrough');
  }

  {
    const r = new SurrogateChunkReconstructor(vault, { unresolvedPolicy: 'throw' });
    assert.throws(
      () => r.push('x [M_EMAIL_deadbeefdeadbeef] y'),
      UnresolvedSurrogateError,
      'unknown surrogate throws under throw policy',
    );
  }

  {
    const r = new SurrogateChunkReconstructor(vault, { unresolvedPolicy: 'redact' });
    const out = r.push('x [M_EMAIL_deadbeefdeadbeef] y') + r.flush();
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
    assert.equal(
      Buffer.concat(chunks).toString('utf8'),
      'data: {"text":"mail alice@example.com done"}\n\n',
      'transform pipeline restores across chunks',
    );
  }

  {
    const r = new SurrogateChunkReconstructor(vault);
    r.push('secret ');
    r.scrub();
    assert.throws(() => r.push('more'), 'scrub blocks reuse');
  }

  TokenVault.resetInstance();
  console.log('streaming.smoke: OK');
}

run().catch((error) => {
  console.error('streaming.smoke: FAILED', error);
  process.exit(1);
});
