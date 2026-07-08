import { z } from 'zod';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ClassifiedSpan, ClassifierClient } from '../core/filters/piiScanner';
import type { GuardModelAssessment, GuardModelClient } from '../core/filters/injectionShield';

const MAX_RESPONSE_BYTES = 1024 * 1024;
const ClassifierResponseSchema = z.object({
    spans: z.array(z.object({
        label: z.string().trim().min(1).max(64),
        start: z.number().int().nonnegative(),
        end: z.number().int().positive(),
        score: z.number().finite().min(0).max(1),
    }).strict()).max(4096),
}).strict();
const GuardResponseSchema = z.object({
    label: z.enum(['benign', 'prompt_injection', 'jailbreak', 'unsafe']),
    score: z.number().finite().min(0).max(1),
}).strict();
const LocalGuardModelSchema = z.object({
    format: z.literal('valence-multinomial-nb-v1'),
    source: z.string().min(1).max(256),
    bias: z.number().finite(),
    threshold: z.number().finite(),
    weights: z.record(z.string().min(1).max(128), z.number().finite()),
}).strict();
const TOKEN_PATTERN = /[a-z0-9]+/g;
const MAX_MODEL_FEATURES = 20_000;
const MAX_CLASSIFIER_TOKENS = 10_000;

interface HttpModelClientOptions {
    readonly url: string;
    readonly apiKey?: string;
    readonly timeoutMs: number;
    readonly request?: typeof fetch;
}

async function postJson(options: HttpModelClientOptions, text: string): Promise<unknown> {
    const request = options.request ?? fetch;
    const response = await request(options.url, {
        method: 'POST',
        headers: {
            'content-type': 'application/json',
            'accept': 'application/json',
            ...(options.apiKey === undefined ? {} : { authorization: `Bearer ${options.apiKey}` }),
        },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(options.timeoutMs),
        redirect: 'error',
    });
    if (!response.ok) {
        throw new Error(`model service rejected request with HTTP ${response.status}`);
    }
    const contentLength = Number(response.headers.get('content-length') ?? 0);
    if (contentLength > MAX_RESPONSE_BYTES) {
        throw new Error('model service response exceeds 1 MiB');
    }
    const body = await response.text();
    if (Buffer.byteLength(body, 'utf8') > MAX_RESPONSE_BYTES) {
        throw new Error('model service response exceeds 1 MiB');
    }
    return JSON.parse(body) as unknown;
}

export class HttpClassifierClient implements ClassifierClient {
    public constructor(private readonly options: HttpModelClientOptions) {}

    public async classify(text: string): Promise<readonly ClassifiedSpan[]> {
        return ClassifierResponseSchema.parse(await postJson(this.options, text)).spans;
    }
}

export class HttpGuardModelClient implements GuardModelClient {
    public constructor(private readonly options: HttpModelClientOptions) {}

    public async assess(text: string): Promise<GuardModelAssessment> {
        return GuardResponseSchema.parse(await postJson(this.options, text));
    }
}

function guardFeatures(text: string): string[] {
    const words = text.normalize('NFKC').toLowerCase().match(TOKEN_PATTERN)?.slice(0, MAX_CLASSIFIER_TOKENS) ?? [];
    const features = [...words];
    for (let index = 0; index + 1 < words.length; index += 1) {
        features.push(`${words[index]}_${words[index + 1]}`);
    }
    return features;
}

export class LocalGuardModelClient implements GuardModelClient {
    private readonly model: z.infer<typeof LocalGuardModelSchema>;

    public constructor(path: string, expectedSha256?: string) {
        const bytes = readFileSync(resolve(path));
        const digest = createHash('sha256').update(bytes).digest('hex');
        if (expectedSha256 !== undefined && digest !== expectedSha256) {
            throw new Error('guard model SHA-256 mismatch');
        }
        const model = LocalGuardModelSchema.parse(JSON.parse(bytes.toString('utf8')));
        if (Object.keys(model.weights).length > MAX_MODEL_FEATURES) {
            throw new Error(`guard model exceeds ${MAX_MODEL_FEATURES} features`);
        }
        this.model = model;
    }

    public assess(text: string): Promise<GuardModelAssessment> {
        let logOdds = this.model.bias;
        for (const feature of guardFeatures(text)) {
            logOdds += this.model.weights[feature] ?? 0;
        }
        const bounded = Math.max(-30, Math.min(30, logOdds));
        const score = 1 / (1 + Math.exp(-bounded));
        return Promise.resolve({
            label: logOdds >= this.model.threshold ? 'prompt_injection' : 'benign',
            score: logOdds >= this.model.threshold ? score : 1 - score,
        });
    }
}
