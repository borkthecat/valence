import { createHash } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { appendFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import type { GuardPolicy } from '../core/filters/injectionShield';

const EMAIL_PATTERN = /[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g;
const PHONE_PATTERN = /(?:\+?\d[\d .()/-]{7,}\d)/g;

export interface ShadowReviewEvent {
    readonly requestId: string;
    readonly sourceId: string;
    readonly policy: GuardPolicy;
    readonly score: number;
    readonly text: string;
}

export function parseShadowReviewSources(raw: string): ReadonlySet<string> {
    return new Set(raw.split(',').map((value) => value.trim()).filter(Boolean));
}

export function redactShadowReviewText(text: string): string {
    return text.replace(EMAIL_PATTERN, '[REDACTED_EMAIL]').replace(PHONE_PATTERN, '[REDACTED_PHONE]');
}

function recordId(sourceId: string, text: string): string {
    return createHash('sha256').update(`${sourceId}\0${text}`).digest('hex');
}

export class ShadowReviewLog {
    private queue: Promise<void> = Promise.resolve();
    private failed: Error | null = null;

    public constructor(private readonly path: string) {
        const absolute = resolve(path);
        mkdirSync(dirname(absolute), { recursive: true, mode: 0o700 });
        this.path = absolute;
    }

    public record(event: ShadowReviewEvent): void {
        const text = redactShadowReviewText(event.text);
        const record = {
            record_id: recordId(event.sourceId, text),
            request_id: event.requestId,
            source_id: event.sourceId,
            policy: event.policy,
            score: event.score,
            text,
        };
        this.queue = this.queue
            .then(() => appendFile(this.path, `${JSON.stringify(record)}\n`, { mode: 0o600 }))
            .catch((error: unknown) => {
                this.failed = error instanceof Error ? error : new Error(String(error));
            });
    }

    public async flush(): Promise<void> {
        await this.queue;
        if (this.failed !== null) {
            throw this.failed;
        }
    }
}

export function createShadowReviewLog(path: string): ShadowReviewLog | null {
    return path.trim().toLowerCase() === 'off' ? null : new ShadowReviewLog(path);
}
