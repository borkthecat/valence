import { SurrogateCategory, type TokenVaultBackend } from '../crypto/tokenVault';
export interface PiiFinding {
    readonly category: SurrogateCategory;
    readonly start: number;
    readonly end: number;
    readonly confidence: number;
    readonly detector: string;
}
export interface PiiDetector {
    readonly name: string;
    detect(text: string): Promise<readonly PiiFinding[]>;
}
export interface PiiScanResult {
    readonly sanitizedText: string;
    readonly findings: readonly PiiFinding[];
    readonly surrogates: readonly string[];
}
export class PiiScanError extends Error {
    public readonly failedDetectors: readonly string[];
    public constructor(failedDetectors: readonly string[], cause?: unknown) {
        super(`PII scan incomplete - detector failure(s): ${failedDetectors.join(', ')}`);
        this.name = 'PiiScanError';
        this.failedDetectors = failedDetectors;
        if (cause !== undefined) {
            (this as {
                cause?: unknown;
            }).cause = cause;
        }
    }
}
interface HeuristicRule {
    readonly id: string;
    readonly category: SurrogateCategory;
    readonly pattern: RegExp;
    readonly confidence: number;
    readonly validate?: (match: string) => boolean;
}
function passesLuhn(digits: string): boolean {
    let sum = 0;
    let doubleNext = false;
    for (let i = digits.length - 1; i >= 0; i -= 1) {
        const char = digits[i];
        if (char === undefined) {
            return false;
        }
        let value = char.charCodeAt(0) - 48;
        if (value < 0 || value > 9) {
            return false;
        }
        if (doubleNext) {
            value *= 2;
            if (value > 9) {
                value -= 9;
            }
        }
        sum += value;
        doubleNext = !doubleNext;
    }
    return sum % 10 === 0;
}
function isValidCreditCard(match: string): boolean {
    const digits = match.replace(/[ -]/g, '');
    if (digits.length < 13 || digits.length > 19) {
        return false;
    }
    if (/^(\d)\1+$/.test(digits)) {
        return false;
    }
    return passesLuhn(digits);
}
function isValidSsn(match: string): boolean {
    const parts = match.split('-');
    const area = parts[0];
    const group = parts[1];
    const serial = parts[2];
    if (area === undefined || group === undefined || serial === undefined) {
        return false;
    }
    const areaNum = Number(area);
    if (areaNum === 0 || areaNum === 666 || areaNum >= 900) {
        return false;
    }
    if (group === '00' || serial === '0000') {
        return false;
    }
    return true;
}
const HEURISTIC_RULES: readonly HeuristicRule[] = [
    {
        id: 'email-rfc-lite',
        category: SurrogateCategory.EMAIL,
        pattern: /[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24}/g,
        confidence: 0.95,
    },
    {
        id: 'ssn-dashed',
        category: SurrogateCategory.SSN,
        pattern: /\b\d{3}-\d{2}-\d{4}\b/g,
        confidence: 0.9,
        validate: isValidSsn,
    },
    {
        id: 'credit-card-luhn',
        category: SurrogateCategory.CREDIT_CARD,
        pattern: /\b\d(?:[ -]?\d){12,18}\b/g,
        confidence: 0.9,
        validate: isValidCreditCard,
    },
    {
        id: 'openai-secret-key',
        category: SurrogateCategory.API_KEY,
        pattern: /\bsk-[A-Za-z0-9_-]{20,512}\b/g,
        confidence: 0.98,
    },
    {
        id: 'anthropic-secret-key',
        category: SurrogateCategory.API_KEY,
        pattern: /\bsk-ant-[A-Za-z0-9_-]{20,512}\b/g,
        confidence: 0.99,
    },
    {
        id: 'github-token',
        category: SurrogateCategory.API_KEY,
        pattern: /\bgh[pousr]_[A-Za-z0-9]{36,255}\b/g,
        confidence: 0.99,
    },
    {
        id: 'aws-access-key-id',
        category: SurrogateCategory.API_KEY,
        pattern: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g,
        confidence: 0.98,
    },
    {
        id: 'slack-token',
        category: SurrogateCategory.ACCESS_TOKEN,
        pattern: /\bxox[baprs]-[A-Za-z0-9-]{10,512}\b/g,
        confidence: 0.98,
    },
    {
        id: 'jwt',
        category: SurrogateCategory.ACCESS_TOKEN,
        pattern: /\beyJ[A-Za-z0-9_-]{8,4096}\.[A-Za-z0-9_-]{8,4096}\.[A-Za-z0-9_-]{8,4096}\b/g,
        confidence: 0.95,
    },
    {
        id: 'private-key-block',
        category: SurrogateCategory.GENERIC_SECRET,
        pattern: /-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----[\s\S]{1,65536}?-----END [A-Z ]{0,20}PRIVATE KEY-----/g,
        confidence: 1,
    },
];
export class HeuristicPiiDetector implements PiiDetector {
    public readonly name = 'heuristic-static';
    private readonly rules: readonly HeuristicRule[];
    public constructor(rules: readonly HeuristicRule[] = HEURISTIC_RULES) {
        for (const rule of rules) {
            if (!rule.pattern.global) {
                throw new TypeError(`HeuristicPiiDetector: rule "${rule.id}" pattern must use the g flag`);
            }
        }
        this.rules = rules;
    }
    public detect(text: string): Promise<readonly PiiFinding[]> {
        const findings: PiiFinding[] = [];
        for (const rule of this.rules) {
            const pattern = new RegExp(rule.pattern.source, rule.pattern.flags);
            for (const match of text.matchAll(pattern)) {
                const value = match[0];
                const start = match.index;
                if (value === undefined || value.length === 0 || start === undefined) {
                    continue;
                }
                if (rule.validate !== undefined && !rule.validate(value)) {
                    continue;
                }
                findings.push({
                    category: rule.category,
                    start,
                    end: start + value.length,
                    confidence: rule.confidence,
                    detector: this.name,
                });
            }
        }
        return Promise.resolve(findings);
    }
}
export interface ClassifiedSpan {
    readonly label: string;
    readonly start: number;
    readonly end: number;
    readonly score: number;
}
export interface ClassifierClient {
    classify(text: string): Promise<readonly ClassifiedSpan[]>;
}
const CLASSIFIER_LABEL_MAP: Readonly<Record<string, SurrogateCategory>> = {
    EMAIL_ADDRESS: SurrogateCategory.EMAIL,
    PHONE_NUMBER: SurrogateCategory.PHONE,
    US_SSN: SurrogateCategory.SSN,
    CREDIT_CARD: SurrogateCategory.CREDIT_CARD,
    IP_ADDRESS: SurrogateCategory.IP_ADDRESS,
    API_KEY: SurrogateCategory.API_KEY,
    ACCESS_TOKEN: SurrogateCategory.ACCESS_TOKEN,
    PASSWORD: SurrogateCategory.PASSWORD,
    PERSON: SurrogateCategory.PERSON_NAME,
};
export class EmbeddingClassifierDetector implements PiiDetector {
    public readonly name: string;
    private readonly client: ClassifierClient;
    private readonly minimumScore: number;
    public constructor(client: ClassifierClient, options: {
        readonly name?: string;
        readonly minimumScore?: number;
    } = {}) {
        this.client = client;
        this.name = options.name ?? 'embedding-classifier';
        this.minimumScore = options.minimumScore ?? 0.5;
    }
    public async detect(text: string): Promise<readonly PiiFinding[]> {
        const spans = await this.client.classify(text);
        const findings: PiiFinding[] = [];
        for (const span of spans) {
            const category = CLASSIFIER_LABEL_MAP[span.label];
            if (category === undefined || span.score < this.minimumScore) {
                continue;
            }
            if (!Number.isInteger(span.start) ||
                !Number.isInteger(span.end) ||
                span.start < 0 ||
                span.end > text.length ||
                span.start >= span.end) {
                continue;
            }
            findings.push({
                category,
                start: span.start,
                end: span.end,
                confidence: Math.min(Math.max(span.score, 0), 1),
                detector: this.name,
            });
        }
        return findings;
    }
}
export class NullClassifierClient implements ClassifierClient {
    public classify(): Promise<readonly ClassifiedSpan[]> {
        return Promise.resolve([]);
    }
}
function resolveOverlaps(findings: readonly PiiFinding[]): PiiFinding[] {
    const sorted = [...findings].sort((a, b) => {
        if (a.start !== b.start) {
            return a.start - b.start;
        }
        const lengthDelta = (b.end - b.start) - (a.end - a.start);
        if (lengthDelta !== 0) {
            return lengthDelta;
        }
        return b.confidence - a.confidence;
    });
    const accepted: PiiFinding[] = [];
    let cursor = 0;
    for (const finding of sorted) {
        if (finding.start >= cursor) {
            accepted.push(finding);
            cursor = finding.end;
        }
    }
    return accepted;
}
export class PiiScanner {
    private readonly vault: TokenVaultBackend;
    private readonly detectors: readonly PiiDetector[];
    public constructor(vault: TokenVaultBackend, detectors: readonly PiiDetector[]) {
        if (detectors.length === 0) {
            throw new RangeError('PiiScanner requires at least one detector');
        }
        this.vault = vault;
        this.detectors = detectors;
    }
    public async scan(text: string): Promise<PiiScanResult> {
        if (text.length === 0) {
            return { sanitizedText: text, findings: [], surrogates: [] };
        }
        const settled = await Promise.allSettled(this.detectors.map((detector) => detector.detect(text)));
        const failed: string[] = [];
        const collected: PiiFinding[] = [];
        let firstCause: unknown;
        settled.forEach((outcome, index) => {
            const detector = this.detectors[index];
            const detectorName = detector?.name ?? `detector#${index}`;
            if (outcome.status === 'fulfilled') {
                collected.push(...outcome.value);
            }
            else {
                failed.push(detectorName);
                if (firstCause === undefined) {
                    firstCause = outcome.reason;
                }
            }
        });
        if (failed.length > 0) {
            throw new PiiScanError(failed, firstCause);
        }
        const accepted = resolveOverlaps(collected);
        let sanitizedText = text;
        const surrogates: string[] = [];
        for (let i = accepted.length - 1; i >= 0; i -= 1) {
            const finding = accepted[i];
            if (finding === undefined) {
                continue;
            }
            const raw = text.slice(finding.start, finding.end);
            const surrogate = await this.vault.tokenize(raw, finding.category);
            surrogates.push(surrogate);
            sanitizedText =
                sanitizedText.slice(0, finding.start) +
                    surrogate +
                    sanitizedText.slice(finding.end);
        }
        return { sanitizedText, findings: accepted, surrogates };
    }
}
