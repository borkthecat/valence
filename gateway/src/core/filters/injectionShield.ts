export interface InjectionMatch {
    readonly ruleId: string;
    readonly description: string;
    readonly weight: number;
    readonly excerpt: string;
    readonly detector: string;
}
export interface InjectionVerdict {
    readonly blocked: boolean;
    readonly score: number;
    readonly threshold: number;
    readonly matches: readonly InjectionMatch[];
}
export interface InjectionDetector {
    readonly name: string;
    detect(normalizedText: string): Promise<readonly InjectionMatch[]>;
}
export class InjectionShieldError extends Error {
    public readonly failedDetectors: readonly string[];
    public constructor(failedDetectors: readonly string[], cause?: unknown) {
        super(`Injection analysis incomplete - detector failure(s): ${failedDetectors.join(', ')}`);
        this.name = 'InjectionShieldError';
        this.failedDetectors = failedDetectors;
        if (cause !== undefined) {
            (this as {
                cause?: unknown;
            }).cause = cause;
        }
    }
}
const EXCERPT_LIMIT = 48;
export function normalizePrompt(text: string): string {
    return text
        .normalize('NFKC')
        .replace(/[\u200B-\u200F\u202A-\u202E\u2060-\u2064\uFEFF]/g, '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}
function excerptAround(text: string, index: number): string {
    const start = Math.max(0, index - 8);
    const slice = text.slice(start, start + EXCERPT_LIMIT);
    return slice.length < EXCERPT_LIMIT ? slice : `${slice}…`;
}
interface InjectionRule {
    readonly id: string;
    readonly description: string;
    readonly pattern: RegExp;
    readonly weight: number;
}
const INJECTION_RULES: readonly InjectionRule[] = [
    {
        id: 'override-previous-instructions',
        description: 'Attempts to void prior/system instructions',
        pattern: /\b(?:ignore|disregard|forget|override|bypass)\b[^.!?]{0,40}\b(?:previous|prior|above|earlier|all|system)\b[^.!?]{0,20}\b(?:instructions?|rules?|prompts?|guidelines?|directives?)\b/,
        weight: 0.8,
    },
    {
        id: 'new-instructions-supersede',
        description: 'Declares new instructions that replace the system prompt',
        pattern: /\b(?:new|real|actual|true)\s+(?:instructions?|rules?|system prompt)\b[^.!?]{0,40}\b(?:supersede|replace|override|take precedence)\b/,
        weight: 0.7,
    },
    {
        id: 'persona-jailbreak',
        description: 'Persona reassignment to an unrestricted agent',
        pattern: /\byou are (?:now|no longer)\b[^.!?]{0,60}\b(?:restrictions?|limitations?|filters?|guidelines?|dan|developer mode|jailbroken)\b/,
        weight: 0.7,
    },
    {
        id: 'do-anything-now',
        description: 'Named jailbreak persona invocation',
        pattern: /\b(?:do anything now|\bdan mode\b|(?:simulate|enable|activate|enter)\s+developer mode|developer mode enabled|aim jailbreak)\b/,
        weight: 0.8,
    },
    {
        id: 'pretend-no-rules',
        description: 'Roleplay framing to shed safety rules',
        pattern: /\b(?:pretend|act as if|imagine)\b[^.!?]{0,40}\b(?:no|without|free of)\b[^.!?]{0,20}\b(?:rules?|restrictions?|filters?|guidelines?)\b/,
        weight: 0.6,
    },
    {
        id: 'system-prompt-exfiltration',
        description: 'Requests disclosure of hidden system instructions',
        pattern: /\b(?:reveal|print|show|repeat|output|display|tell me)\b[^.!?]{0,40}\b(?:system prompt|initial instructions?|hidden instructions?|original instructions?|your instructions?)\b/,
        weight: 0.8,
    },
    {
        id: 'control-token-smuggling',
        description: 'Raw chat-template control tokens embedded in user text',
        pattern: /<\|(?:im_start|im_end|system|endoftext|assistant)\|>|\[\/?(?:inst|system)\]|<<sys>>/,
        weight: 0.9,
    },
    {
        id: 'markdown-header-role-injection',
        description: 'Markdown/pseudo-role header impersonating a system turn',
        pattern: /(?:^|\s)#{1,4}\s*(?:system|assistant)\s*(?:message|prompt|:)/,
        weight: 0.5,
    },
    {
        id: 'base64-payload-carrier',
        description: 'Long base64 blob - common obfuscated-instruction carrier',
        pattern: /\b[a-z0-9+/]{120,}={0,2}\b/,
        weight: 0.3,
    },
    {
        id: 'markdown-image-exfil',
        description: 'Markdown image beacon with query-string data channel',
        pattern: /!\[[^\]]*\]\(https?:\/\/[^)\s]{1,200}\?[^)\s]{1,400}\)/,
        weight: 0.6,
    },
    {
        id: 'tool-result-forgery',
        description: 'Fabricated tool/function-result framing inside user text',
        pattern: /\b(?:tool|function)[ _-]?(?:result|output|response)\b[^.!?]{0,30}\b(?:says?|returned|instructs?)\b[^.!?]{0,40}\b(?:you must|you should|ignore|execute)\b/,
        weight: 0.6,
    },
];
export class HeuristicInjectionDetector implements InjectionDetector {
    public readonly name = 'heuristic-injection';
    private readonly rules: readonly InjectionRule[];
    public constructor(rules: readonly InjectionRule[] = INJECTION_RULES) {
        this.rules = rules;
    }
    public detect(normalizedText: string): Promise<readonly InjectionMatch[]> {
        const matches: InjectionMatch[] = [];
        for (const rule of this.rules) {
            const match = rule.pattern.exec(normalizedText);
            if (match === null) {
                continue;
            }
            matches.push({
                ruleId: rule.id,
                description: rule.description,
                weight: rule.weight,
                excerpt: excerptAround(normalizedText, match.index),
                detector: this.name,
            });
        }
        return Promise.resolve(matches);
    }
}
export interface GuardModelAssessment {
    readonly label: string;
    readonly score: number;
}
export interface GuardModelClient {
    assess(text: string): Promise<GuardModelAssessment>;
}
const HOSTILE_GUARD_LABELS: ReadonlySet<string> = new Set([
    'prompt_injection',
    'jailbreak',
    'unsafe',
]);
export class GuardModelDetector implements InjectionDetector {
    public readonly name: string;
    private readonly client: GuardModelClient;
    private readonly minimumScore: number;
    public constructor(client: GuardModelClient, options: {
        readonly name?: string;
        readonly minimumScore?: number;
    } = {}) {
        this.client = client;
        this.name = options.name ?? 'guard-model';
        this.minimumScore = options.minimumScore ?? 0.5;
    }
    public async detect(normalizedText: string): Promise<readonly InjectionMatch[]> {
        const assessment = await this.client.assess(normalizedText);
        const label = assessment.label.toLowerCase();
        if (!HOSTILE_GUARD_LABELS.has(label) || assessment.score < this.minimumScore) {
            return [];
        }
        return [
            {
                ruleId: `guard-model:${label}`,
                description: `Guard model classified prompt as "${label}" with score ${assessment.score.toFixed(4)}`,
                weight: 1,
                excerpt: excerptAround(normalizedText, 0),
                detector: this.name,
            },
        ];
    }
}
export class NullGuardModelClient implements GuardModelClient {
    public assess(): Promise<GuardModelAssessment> {
        return Promise.resolve({ label: 'benign', score: 0 });
    }
}
export interface InjectionShieldOptions {
    readonly blockThreshold?: number;
}
export class InjectionShield {
    private readonly detectors: readonly InjectionDetector[];
    private readonly blockThreshold: number;
    public constructor(detectors: readonly InjectionDetector[], options: InjectionShieldOptions = {}) {
        if (detectors.length === 0) {
            throw new RangeError('InjectionShield requires at least one detector');
        }
        const threshold = options.blockThreshold ?? 0.8;
        if (!(threshold > 0)) {
            throw new RangeError('blockThreshold must be a positive number');
        }
        this.detectors = detectors;
        this.blockThreshold = threshold;
    }
    public async evaluate(rawText: string): Promise<InjectionVerdict> {
        const normalized = normalizePrompt(rawText);
        if (normalized.length === 0) {
            return {
                blocked: false,
                score: 0,
                threshold: this.blockThreshold,
                matches: [],
            };
        }
        const settled = await Promise.allSettled(this.detectors.map((detector) => detector.detect(normalized)));
        const failed: string[] = [];
        const allMatches: InjectionMatch[] = [];
        let score = 0;
        let firstCause: unknown;
        settled.forEach((outcome, index) => {
            const detector = this.detectors[index];
            const detectorName = detector?.name ?? `detector#${index}`;
            if (outcome.status === 'rejected') {
                failed.push(detectorName);
                if (firstCause === undefined) {
                    firstCause = outcome.reason;
                }
                return;
            }
            const distinctRules = new Map<string, InjectionMatch>();
            for (const match of outcome.value) {
                if (!distinctRules.has(match.ruleId)) {
                    distinctRules.set(match.ruleId, match);
                }
            }
            let detectorScore = 0;
            for (const match of distinctRules.values()) {
                detectorScore += match.weight;
                allMatches.push(match);
            }
            score = Math.max(score, detectorScore);
        });
        if (failed.length > 0) {
            throw new InjectionShieldError(failed, firstCause);
        }
        return {
            blocked: score >= this.blockThreshold,
            score,
            threshold: this.blockThreshold,
            matches: allMatches,
        };
    }
}
