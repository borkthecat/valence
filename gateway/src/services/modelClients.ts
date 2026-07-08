import { z } from 'zod';
import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
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
const LinearGuardModelSchema = z.object({
    format: z.literal('valence-linear-tfidf-v1'),
    source: z.string().min(1).max(256),
    language: z.literal('en'),
    trainingRecords: z.number().int().positive().max(1_000_000),
    bias: z.number().finite(),
    threshold: z.number().finite(),
    features: z.record(
        z.string().min(3).max(128),
        z.tuple([z.number().finite().positive(), z.number().finite()]),
    ),
}).strict();
const GuardModelSchema = z.union([LocalGuardModelSchema, LinearGuardModelSchema]);
const TOKEN_PATTERN = /[a-z0-9]+/g;
const MAX_MODEL_FEATURES = 150_000;
const MAX_MODEL_BYTES = 16 * 1024 * 1024;
const MAX_CLASSIFIER_TOKENS = 10_000;
const MAX_TOKEN_LENGTH = 60;
const MAX_CHARACTER_TEXT = 16_384;

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

function* linearGuardFeatures(text: string): Generator<string> {
    const words = text.normalize('NFKC').toLowerCase().match(TOKEN_PATTERN)
        ?.slice(0, MAX_CLASSIFIER_TOKENS)
        .map((word) => word.slice(0, MAX_TOKEN_LENGTH)) ?? [];
    for (const word of words) {
        yield `w:${word}`;
    }
    for (let index = 0; index + 1 < words.length; index += 1) {
        yield `w:${words[index]}_${words[index + 1]}`;
    }
    const characterText = words.join(' ').slice(0, MAX_CHARACTER_TEXT);
    for (const size of [3, 4, 5]) {
        for (let index = 0; index + size <= characterText.length; index += 1) {
            yield `c:${characterText.slice(index, index + size)}`;
        }
    }
}

export class LocalGuardModelClient implements GuardModelClient {
    private readonly model: z.infer<typeof GuardModelSchema>;

    public constructor(path: string, expectedSha256?: string) {
        const modelPath = resolve(path);
        if (statSync(modelPath).size > MAX_MODEL_BYTES) {
            throw new Error('guard model exceeds 16 MiB');
        }
        const bytes = readFileSync(modelPath);
        const digest = createHash('sha256').update(bytes).digest('hex');
        if (expectedSha256 !== undefined && digest !== expectedSha256) {
            throw new Error('guard model SHA-256 mismatch');
        }
        const model = GuardModelSchema.parse(JSON.parse(bytes.toString('utf8')));
        const featureCount = model.format === 'valence-linear-tfidf-v1'
            ? Object.keys(model.features).length
            : Object.keys(model.weights).length;
        if (featureCount > MAX_MODEL_FEATURES) {
            throw new Error(`guard model exceeds ${MAX_MODEL_FEATURES} features`);
        }
        this.model = model;
    }

    public assess(text: string): Promise<GuardModelAssessment> {
        if (this.model.format === 'valence-linear-tfidf-v1') {
            return Promise.resolve(this.assessLinear(text));
        }
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

    private assessLinear(text: string): GuardModelAssessment {
        const model = this.model;
        if (model.format !== 'valence-linear-tfidf-v1') {
            throw new Error('invalid linear guard model');
        }
        const counts = new Map<string, number>();
        for (const feature of linearGuardFeatures(text)) {
            if (model.features[feature] !== undefined) {
                counts.set(feature, (counts.get(feature) ?? 0) + 1);
            }
        }
        let squaredNorm = 0;
        let weightedSum = 0;
        for (const [feature, count] of counts) {
            const parameters = model.features[feature];
            if (parameters === undefined) continue;
            const value = (1 + Math.log(count)) * parameters[0];
            squaredNorm += value * value;
            weightedSum += value * parameters[1];
        }
        const decision = model.bias + (squaredNorm === 0 ? 0 : weightedSum / Math.sqrt(squaredNorm));
        const bounded = Math.max(-30, Math.min(30, decision));
        const score = 1 / (1 + Math.exp(-bounded));
        return {
            label: decision >= model.threshold ? 'prompt_injection' : 'benign',
            score: decision >= model.threshold ? score : 1 - score,
        };
    }
}
