import { StringDecoder } from 'node:string_decoder';
import { Transform } from 'node:stream';
import { SURROGATE_PATTERN, TokenVault } from '../crypto/tokenVault';
export type UnresolvedSurrogatePolicy = 'throw' | 'redact' | 'passthrough';
export const REDACTED_PLACEHOLDER = '[REDACTED]';
export const MAX_SURROGATE_LENGTH = 1 + 2 + 32 + 1 + 16 + 1;
const VIABLE_PREFIX_PATTERN = /^\[(?:M(?:_(?:[A-Z_]{1,32}(?:_[0-9a-f]{0,16})?)?)?)?$/;
const OPEN_BRACKET = 0x5b;
export class UnresolvedSurrogateError extends Error {
    public readonly marker: string;
    public constructor(marker: string) {
        super(`Stream reconstitution failed - surrogate has no vault entry (expired TTL or foreign marker): ${marker}`);
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
    readonly unresolvedPolicy?: UnresolvedSurrogatePolicy;
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
    public push(chunk: Buffer | Uint8Array | string): string {
        this.assertUsable();
        let text: string;
        if (typeof chunk === 'string') {
            text = chunk;
            this.bytesIn += Buffer.byteLength(chunk, 'utf8');
        }
        else {
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
    public flush(): string {
        this.assertUsable();
        const tail = this.decoder.end();
        this.pending = this.resolveCompleteMarkers(this.pending + tail);
        const output = this.pending;
        this.pending = '';
        this.charsEmitted += output.length;
        return output;
    }
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
            throw new Error('SurrogateChunkReconstructor: instance has been scrubbed and cannot be reused');
        }
    }
    private resolveCompleteMarkers(text: string): string {
        const pattern = new RegExp(SURROGATE_PATTERN.source, SURROGATE_PATTERN.flags);
        return text.replace(pattern, (marker) => {
            const inScope = this.allowedSurrogates === null || this.allowedSurrogates.has(marker);
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
export function createReconstitutionStream(reconstructor: SurrogateChunkReconstructor): Transform {
    return new Transform({
        readableObjectMode: false,
        writableObjectMode: false,
        transform(chunk: Buffer, _encoding, callback): void {
            try {
                const output = reconstructor.push(chunk);
                if (output.length > 0) {
                    callback(null, output);
                }
                else {
                    callback();
                }
            }
            catch (error) {
                callback(error instanceof Error ? error : new Error(String(error)));
            }
        },
        flush(callback): void {
            try {
                const output = reconstructor.flush();
                if (output.length > 0) {
                    callback(null, output);
                }
                else {
                    callback();
                }
            }
            catch (error) {
                callback(error instanceof Error ? error : new Error(String(error)));
            }
        },
    });
}
