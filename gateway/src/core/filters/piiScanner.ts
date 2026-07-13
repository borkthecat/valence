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
    readonly captureGroup?: number;
    readonly validate?: (match: string, text: string, start: number) => boolean;
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
function isValidPhone(match: string, text: string, start: number): boolean {
    const base = match.replace(/\s*(?:x|ext\.?|extension)\s*\d{1,6}$/i, '');
    if (
        /^\d{3}[- ]\d{2,3}[- ]\d{3,4}$/.test(base)
        || /^\d{4}(?:[ -]\d{4}){2,3}$/.test(base)
        || /^(?:\d{1,3}\.){3}\d{1,3}$/.test(base)
        || /^(?:\d{1,2}\.){2}(?:19|20)\d{2}$/.test(base)
        || isValidCreditCard(base)
    ) {
        return false;
    }
    const digits = base.replace(/\D/g, '');
    if (digits.length < 8 || digits.length > 15 || /^(\d)\1+$/.test(digits)) {
        return false;
    }
    if (digits.length <= 9) {
        const context = text.slice(Math.max(0, start - 48), Math.min(text.length, start + match.length + 32));
        if (!/\b(?:call|contact|fax|mobile|phone|tel|telephone|whatsapp)\b/i.test(context)) {
            return false;
        }
    }
    return true;
}
function isValidIpv4(match: string): boolean {
    const octets = match.split('.');
    return octets.length === 4 && octets.every((octet) => {
        if (!/^\d{1,3}$/.test(octet)) {
            return false;
        }
        return Number(octet) <= 255 && (octet === '0' || !octet.startsWith('0'));
    });
}
function shannonEntropy(value: string): number {
    const counts = new Map<string, number>();
    for (const character of value) {
        counts.set(character, (counts.get(character) ?? 0) + 1);
    }
    let entropy = 0;
    for (const count of counts.values()) {
        const probability = count / value.length;
        entropy -= probability * Math.log2(probability);
    }
    return entropy;
}
function characterClasses(value: string): number {
    return [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((pattern) => pattern.test(value)).length;
}
function isLikelyAssignedSecret(match: string): boolean {
    const normalized = match.normalize('NFKC');
    if (/^(?:password|changeme|welcome|example|placeholder|unknown|undefined|default)\d*[!?.]*$/i.test(normalized)) {
        return false;
    }
    return normalized.length >= 10
        && characterClasses(normalized) >= 2
        && shannonEntropy(normalized) >= 3.0;
}
function isLikelyContextualIdentifier(match: string): boolean {
    const normalized = match.normalize('NFKC');
    if (/^(?:none|null|unknown|example|sample|test|default|n\/a)$/i.test(normalized)) {
        return false;
    }
    const classes = characterClasses(normalized);
    return normalized.length >= 6
        && (classes >= 2 || /^\d{8,24}$/.test(normalized))
        && shannonEntropy(normalized) >= 2.2;
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
        id: 'ssn-spaced-contextual',
        category: SurrogateCategory.SSN,
        pattern: /\b(?:SSN|social security(?: number)?)\s*[:=(,-]?\s*(\d{3} \d{3} \d{3})\b/gi,
        confidence: 0.85,
        captureGroup: 1,
    },
    {
        id: 'phone-international',
        category: SurrogateCategory.PHONE,
        pattern: /(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?|\d{2,4}[ .-]){1,3}\d{3,4}(?:\s*(?:x|ext\.?|extension)\s*\d{1,6})?(?!\w|[ .-]\d|\s*(?:x|ext\.?|extension)\s*\d)/gi,
        confidence: 0.75,
        validate: isValidPhone,
    },
    {
        id: 'ipv4',
        category: SurrogateCategory.IP_ADDRESS,
        pattern: /(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)/g,
        confidence: 0.9,
        validate: isValidIpv4,
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
        id: 'contextual-api-key',
        category: SurrogateCategory.API_KEY,
        pattern: /\bapi[_ -]?keys?\s*(?:[:=,]|\bis\b)?\s*["'(\[]?([A-Za-z0-9][A-Za-z0-9._-]{19,511})/gi,
        confidence: 0.9,
        captureGroup: 1,
    },
    {
        id: 'contextual-password-assignment',
        category: SurrogateCategory.PASSWORD,
        pattern: /\bpassword\s*[:=]\s*["'(\[]?([^\s"',;)\]]{8,128})/gi,
        confidence: 0.9,
        captureGroup: 1,
        validate: isLikelyAssignedSecret,
    },
    {
        id: 'contextual-password-example',
        category: SurrogateCategory.PASSWORD,
        pattern: /\bpasswords?\s+(?:like|such as)\s+["'(\[]?([^\s"',;)\]]{8,128})/gi,
        confidence: 0.85,
        captureGroup: 1,
        validate: isLikelyAssignedSecret,
    },
    {
        id: 'contextual-generic-identifier',
        category: SurrogateCategory.GENERIC_SECRET,
        pattern: /\b(?:account|customer|employee|device|member|patient|medical[ _-]?record|health[ _-]?plan|license[ _-]?plate|vehicle|tax|national|user)[ _-]?(?:id|number|identifier)\s*(?:[:=,]|\bis\b)?\s*["'(\[]?([A-Za-z0-9](?:[A-Za-z0-9._:/-]{4,61}[A-Za-z0-9])?)/gi,
        confidence: 0.82,
        captureGroup: 1,
        validate: isLikelyContextualIdentifier,
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
                const fullMatch = match[0];
                const value = rule.captureGroup === undefined ? fullMatch : match[rule.captureGroup];
                const fullStart = match.index;
                if (value === undefined || value.length === 0 || fullStart === undefined) {
                    continue;
                }
                const relativeStart = rule.captureGroup === undefined ? 0 : fullMatch.lastIndexOf(value);
                if (relativeStart < 0) continue;
                const start = fullStart + relativeStart;
                if (rule.validate !== undefined && !rule.validate(value, text, start)) {
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
    EMAIL: SurrogateCategory.EMAIL,
    EMAIL_ADDRESS: SurrogateCategory.EMAIL,
    PHONE: SurrogateCategory.PHONE,
    PHONE_NUMBER: SurrogateCategory.PHONE,
    SSN: SurrogateCategory.SSN,
    US_SSN: SurrogateCategory.SSN,
    CREDIT_CARD_NUMBER: SurrogateCategory.CREDIT_CARD,
    CREDIT_CARD: SurrogateCategory.CREDIT_CARD,
    IP: SurrogateCategory.IP_ADDRESS,
    IPV4: SurrogateCategory.IP_ADDRESS,
    IPV6: SurrogateCategory.IP_ADDRESS,
    IP_ADDRESS: SurrogateCategory.IP_ADDRESS,
    API_KEY: SurrogateCategory.API_KEY,
    ACCESS_TOKEN: SurrogateCategory.ACCESS_TOKEN,
    PASSWORD: SurrogateCategory.PASSWORD,
    PERSON: SurrogateCategory.PERSON_NAME,
    PERSON_NAME: SurrogateCategory.PERSON_NAME,
    NAME: SurrogateCategory.PERSON_NAME,
    FIRST_NAME: SurrogateCategory.PERSON_NAME,
    LAST_NAME: SurrogateCategory.PERSON_NAME,
    ADDRESS: SurrogateCategory.GENERIC_SECRET,
    STREET_ADDRESS: SurrogateCategory.GENERIC_SECRET,
    CITY: SurrogateCategory.GENERIC_SECRET,
    STATE: SurrogateCategory.GENERIC_SECRET,
    COUNTRY: SurrogateCategory.GENERIC_SECRET,
    POSTCODE: SurrogateCategory.GENERIC_SECRET,
    COORDINATE: SurrogateCategory.GENERIC_SECRET,
    DATE: SurrogateCategory.GENERIC_SECRET,
    DATE_TIME: SurrogateCategory.GENERIC_SECRET,
    DATE_OF_BIRTH: SurrogateCategory.GENERIC_SECRET,
    TIME: SurrogateCategory.GENERIC_SECRET,
    URL: SurrogateCategory.GENERIC_SECRET,
    COMPANY_NAME: SurrogateCategory.GENERIC_SECRET,
    ACCOUNT_NUMBER: SurrogateCategory.GENERIC_SECRET,
    BANK_ROUTING_NUMBER: SurrogateCategory.GENERIC_SECRET,
    BIOMETRIC_IDENTIFIER: SurrogateCategory.GENERIC_SECRET,
    CERTIFICATE_LICENSE_NUMBER: SurrogateCategory.GENERIC_SECRET,
    CUSTOMER_ID: SurrogateCategory.GENERIC_SECRET,
    CVV: SurrogateCategory.GENERIC_SECRET,
    DEVICE_IDENTIFIER: SurrogateCategory.GENERIC_SECRET,
    EMPLOYEE_ID: SurrogateCategory.GENERIC_SECRET,
    HEALTH_PLAN_BENEFICIARY_NUMBER: SurrogateCategory.GENERIC_SECRET,
    LICENSE_PLATE: SurrogateCategory.GENERIC_SECRET,
    MEDICAL_RECORD_NUMBER: SurrogateCategory.GENERIC_SECRET,
    NATIONAL_ID: SurrogateCategory.GENERIC_SECRET,
    SWIFT_BIC: SurrogateCategory.GENERIC_SECRET,
    TAX_ID: SurrogateCategory.GENERIC_SECRET,
    UNIQUE_IDENTIFIER: SurrogateCategory.GENERIC_SECRET,
    USER_NAME: SurrogateCategory.GENERIC_SECRET,
    VEHICLE_IDENTIFIER: SurrogateCategory.GENERIC_SECRET,
};
export class EmbeddingClassifierDetector implements PiiDetector {
    public readonly name: string;
    private readonly client: ClassifierClient;
    private readonly minimumScore: number;
    private readonly categoryMinimumScores: Readonly<Partial<Record<SurrogateCategory, number>>>;
    private readonly alignPersonNameBoundaries: boolean;
    public constructor(client: ClassifierClient, options: {
        readonly name?: string;
        readonly minimumScore?: number;
        readonly categoryMinimumScores?: Readonly<Partial<Record<SurrogateCategory, number>>>;
        readonly alignPersonNameBoundaries?: boolean;
    } = {}) {
        this.client = client;
        this.name = options.name ?? 'embedding-classifier';
        this.minimumScore = options.minimumScore ?? 0.5;
        this.categoryMinimumScores = options.categoryMinimumScores ?? {};
        this.alignPersonNameBoundaries = options.alignPersonNameBoundaries ?? true;
    }
    public async detect(text: string): Promise<readonly PiiFinding[]> {
        const spans = await this.client.classify(text);
        const findings: PiiFinding[] = [];
        for (const span of spans) {
            const category = CLASSIFIER_LABEL_MAP[span.label];
            if (category === undefined || span.score < (this.categoryMinimumScores[category] ?? this.minimumScore)) {
                continue;
            }
            if (!Number.isInteger(span.start) ||
                !Number.isInteger(span.end) ||
                span.start < 0 ||
                span.end > text.length ||
                span.start >= span.end) {
                continue;
            }
            const boundaries = category === SurrogateCategory.PERSON_NAME && this.alignPersonNameBoundaries
                ? alignUnicodeWordBoundaries(text, span.start, span.end)
                : { start: span.start, end: span.end };
            findings.push({
                category,
                start: boundaries.start,
                end: boundaries.end,
                confidence: Math.min(Math.max(span.score, 0), 1),
                detector: this.name,
            });
        }
        return findings;
    }
}

function alignUnicodeWordBoundaries(text: string, initialStart: number, initialEnd: number): { start: number; end: number } {
    const tokenCharacter = /[\p{L}\p{M}'\u2019-]/u;
    let start = initialStart;
    let end = initialEnd;
    while (start > 0 && tokenCharacter.test(text[start - 1] ?? '')) start -= 1;
    while (end < text.length && tokenCharacter.test(text[end] ?? '')) end += 1;
    return end - start <= 128 ? { start, end } : { start: initialStart, end: initialEnd };
}

export function parsePiiCategoryThresholds(value: string): Readonly<Partial<Record<SurrogateCategory, number>>> {
    const parsed: unknown = JSON.parse(value);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new TypeError('PII_CLASSIFIER_LABEL_THRESHOLDS must be a JSON object');
    }
    const categories = new Set<string>(Object.values(SurrogateCategory));
    const thresholds: Partial<Record<SurrogateCategory, number>> = {};
    for (const [category, threshold] of Object.entries(parsed)) {
        if (!categories.has(category) || typeof threshold !== 'number' || threshold < 0 || threshold > 1) {
            throw new RangeError(`invalid PII classifier threshold for ${category}`);
        }
        thresholds[category as SurrogateCategory] = threshold;
    }
    return thresholds;
}
export class NullClassifierClient implements ClassifierClient {
    public classify(): Promise<readonly ClassifiedSpan[]> {
        return Promise.resolve([]);
    }
}
export function resolvePiiFindings(findings: readonly PiiFinding[]): PiiFinding[] {
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
        const accepted = resolvePiiFindings(collected);
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
