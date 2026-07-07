/**
 * Valence Gateway - Streaming Surrogate Reconstitution
 *
 * The upstream provider streams responses token-by-token (SSE). Because
 * the outbound prompt was sanitized, the model may echo vault surrogates
 * (`[M_EMAIL_9f2c41d0a7b3e815]`) back in its output - and the transport
 * is free to fragment them anywhere: one chunk may end with `…[M_EM` and
 * the next begin with `AIL_92b…`. A naive per-chunk regex pass would leak
 * the split halves downstream unrestored.
 *
 * `SurrogateChunkReconstructor` solves this with bounded holdback:
 *
 *  1. Bytes are decoded with a stateful `StringDecoder`, so multi-byte
 *     UTF-8 sequences split across chunks never surface as U+FFFD.
 *  2. Every complete surrogate in the working buffer is resolved through
 *     the TokenVault immediately.
 *  3. Only the shortest suffix that could still be the *prefix of an
 *     unfinished surrogate* is retained (≤ MAX_SURROGATE_LENGTH chars);
 *     everything before it is emitted at once. Memory is therefore O(1)
 *     in stream length - the holdback can never exceed one marker.
 *  4. `flush()` drains the decoder and emits any dangling partial marker
 *     verbatim (a truncated stream cannot be resolved, only surfaced).
 *
 * This class operates on the *text channel* of the stream. The pipeline
 * layer that owns SSE/JSON framing extracts delta text, feeds it here,
 * and splices the reconstituted output back into its frames.
 *
 * Unresolved-complete-marker policy is injectable because the correct
 * behaviour is SECURITY_MODE-dependent: FAIL_CLOSED deployments throw
 * (`UnresolvedSurrogateError`), terminating the stream via the global
 * error boundary rather than shipping a marker of unknown provenance.
 */

import { StringDecoder } from 'node:string_decoder';
import { Transform } from 'node:stream';
import { SURROGATE_PATTERN, TokenVault } from '../crypto/tokenVault';

/** Behaviour when a syntactically complete marker has no vault entry. */
export type UnresolvedSurrogatePolicy = 'throw' | 'redact' | 'passthrough';

/** Emitted in place of unresolvable markers under the 'redact' policy. */
export const REDACTED_PLACEHOLDER = '[REDACTED]';

/**
 * Upper bound of a well-formed surrogate:
 * '[' + 'M_' + category (≤ 32) + '_' + 16 hex + ']'.
 * Anything longer without a closing bracket is provably not a surrogate
 * and is released downstream instead of being held back.
 */
export const MAX_SURROGATE_LENGTH = 1 + 2 + 32 + 1 + 16 + 1;

/**
 * Matches every proper prefix of the surrogate grammar
 * `\[M_[A-Z_]+_[0-9a-f]{16}\]` (the complete form is handled by
 * SURROGATE_PATTERN before holdback is computed, so this never needs to
 * accept a closing bracket).
 */
const VIABLE_PREFIX_PATTERN =
  /^\[(?:M(?:_(?:[A-Z_]{1,32}(?:_[0-9a-f]{0,16})?)?)?)?$/;

const OPEN_BRACKET = 0x5b;

export class UnresolvedSurrogateError extends Error {
  /** The marker text, safe to log: surrogates carry no sensitive data. */
  public readonly marker: string;

  public constructor(marker: string) {
    super(
      `Stream reconstitution failed - surrogate has no vault entry (expired TTL or foreign marker): ${marker}`,
    );
    this.name = 'UnresolvedSurrogateError';
    this.marker = marker;
  }
}

export interface ReconstructorStats {
  readonly bytesIn: number;
  readonly charsEmitted: number;
  readonly surrogatesRestored: number;
  readonly surrogatesRedacted: number;
  readonly surrogatesPassedThrough: number;
}

export interface ReconstructorOptions {
  /** Default 'throw' - the only posture consistent with FAIL_CLOSED. */
  readonly unresolvedPolicy?: UnresolvedSurrogatePolicy;
  /**
   * Per-request restoration scope. When provided, ONLY these surrogates
   * may resolve through the vault; any other marker, even one with a
   * live vault entry minted for a different request, follows the
   * unresolved policy instead. This is the cross-tenant contamination
   * guard: a response stream can never restore data it did not mask.
   */
  readonly allowedSurrogates?: ReadonlySet<string>;
}

export class SurrogateChunkReconstructor {
  private readonly vault: TokenVault;
  private readonly unresolvedPolicy: UnresolvedSurrogatePolicy;
  private readonly allowedSurrogates: ReadonlySet<string> | null;

  private decoder: StringDecoder;
  private pending = '';
  private destroyed = false;

  private bytesIn = 0;
  private charsEmitted = 0;
  private surrogatesRestored = 0;
  private surrogatesRedacted = 0;
  private surrogatesPassedThrough = 0;

  public constructor(vault: TokenVault, options: ReconstructorOptions = {}) {
    this.vault = vault;
    this.unresolvedPolicy = options.unresolvedPolicy ?? 'throw';
    this.allowedSurrogates = options.allowedSurrogates ?? null;
    this.decoder = new StringDecoder('utf8');
  }

  /**
   * Ingests one transport chunk and returns every character that is now
   * safe to forward (may be empty while a potential marker is pending).
   *
   * Buffers pass through the stateful UTF-8 decoder; strings are appended
   * as-is. A single stream must not interleave the two forms, since a
   * string arriving between the halves of a split multi-byte character
   * would corrupt decoder state.
   */
  public push(chunk: Buffer | Uint8Array | string): string {
    this.assertUsable();

    let text: string;
    if (typeof chunk === 'string') {
      text = chunk;
      this.bytesIn += Buffer.byteLength(chunk, 'utf8');
    } else {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      this.bytesIn += buffer.length;
      text = this.decoder.write(buffer);
    }

    if (text.length === 0) {
      return '';
    }

    this.pending = this.resolveCompleteMarkers(this.pending + text);
    return this.emitReleasable();
  }

  /**
   * Ends the stream: drains any bytes retained by the decoder, resolves
   * final complete markers, and releases everything - including a
   * dangling partial marker, which is emitted verbatim because a
   * truncated upstream stream is a transport fault, not a leak (partial
   * markers contain no sensitive data by construction).
   */
  public flush(): string {
    this.assertUsable();

    const tail = this.decoder.end();
    this.pending = this.resolveCompleteMarkers(this.pending + tail);

    const output = this.pending;
    this.pending = '';
    this.charsEmitted += output.length;
    return output;
  }

  /**
   * Irreversibly clears buffered plaintext. Called by the global error
   * boundary when a request dies mid-stream so reconstituted PII does
   * not linger on the heap awaiting GC. (JS strings cannot be zeroed in
   * place; dropping every reference is the strongest available scrub.)
   */
  public scrub(): void {
    this.pending = '';
    this.decoder = new StringDecoder('utf8');
    this.destroyed = true;
  }

  public get stats(): ReconstructorStats {
    return Object.freeze({
      bytesIn: this.bytesIn,
      charsEmitted: this.charsEmitted,
      surrogatesRestored: this.surrogatesRestored,
      surrogatesRedacted: this.surrogatesRedacted,
      surrogatesPassedThrough: this.surrogatesPassedThrough,
    });
  }

  private assertUsable(): void {
    if (this.destroyed) {
      throw new Error(
        'SurrogateChunkReconstructor: instance has been scrubbed and cannot be reused',
      );
    }
  }

  private resolveCompleteMarkers(text: string): string {
    // SURROGATE_PATTERN carries the g flag; a fresh copy per call keeps
    // lastIndex state out of concurrent request paths.
    const pattern = new RegExp(SURROGATE_PATTERN.source, SURROGATE_PATTERN.flags);
    return text.replace(pattern, (marker) => {
      // Scope check precedes the vault lookup: an out-of-scope marker is
      // handled identically to an unknown one, so timing and output never
      // reveal whether a foreign surrogate exists in the vault.
      const inScope =
        this.allowedSurrogates === null || this.allowedSurrogates.has(marker);
      const raw = inScope ? this.vault.detokenize(marker) : null;
      if (raw !== null) {
        this.surrogatesRestored += 1;
        return raw;
      }
      switch (this.unresolvedPolicy) {
        case 'throw':
          throw new UnresolvedSurrogateError(marker);
        case 'redact':
          this.surrogatesRedacted += 1;
          return REDACTED_PLACEHOLDER;
        case 'passthrough':
          this.surrogatesPassedThrough += 1;
          return marker;
      }
    });
  }

  /**
   * Releases everything except the longest suffix that is still a viable
   * partial marker. Scanning is confined to the last MAX_SURROGATE_LENGTH
   * characters: a bracket earlier than that already exceeds the maximum
   * marker length without closing, so it cannot be a surrogate.
   */
  private emitReleasable(): string {
    const holdbackStart = this.findHoldbackStart();
    if (holdbackStart === 0) {
      return '';
    }
    const releasable = this.pending.slice(0, holdbackStart);
    this.pending = this.pending.slice(holdbackStart);
    this.charsEmitted += releasable.length;
    return releasable;
  }

  private findHoldbackStart(): number {
    const windowStart = Math.max(0, this.pending.length - MAX_SURROGATE_LENGTH);
    for (let i = windowStart; i < this.pending.length; i += 1) {
      if (this.pending.charCodeAt(i) === OPEN_BRACKET) {
        const suffix = this.pending.slice(i);
        if (VIABLE_PREFIX_PATTERN.test(suffix)) {
          return i;
        }
      }
    }
    return this.pending.length;
  }
}

/**
 * Wraps a reconstructor as a byte-in/text-out Transform for direct use in
 * `pipeline(upstream, reconstitutionStream, clientResponse)`. Errors from
 * the reconstructor (including UnresolvedSurrogateError under 'throw')
 * propagate as stream errors, which the pipeline layer routes to the
 * global fail-closed error boundary.
 */
export function createReconstitutionStream(
  reconstructor: SurrogateChunkReconstructor,
): Transform {
  return new Transform({
    readableObjectMode: false,
    writableObjectMode: false,
    transform(chunk: Buffer, _encoding, callback): void {
      try {
        const output = reconstructor.push(chunk);
        if (output.length > 0) {
          callback(null, output);
        } else {
          callback();
        }
      } catch (error) {
        callback(error instanceof Error ? error : new Error(String(error)));
      }
    },
    flush(callback): void {
      try {
        const output = reconstructor.flush();
        if (output.length > 0) {
          callback(null, output);
        } else {
          callback();
        }
      } catch (error) {
        callback(error instanceof Error ? error : new Error(String(error)));
      }
    },
  });
}
