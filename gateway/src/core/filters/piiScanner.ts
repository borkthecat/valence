/**
 * Valence Gateway - PII Scanning & Redaction Engine
 *
 * Detects sensitive values in outbound prompt text and swaps them for
 * TokenVault surrogates before the payload crosses the trust boundary.
 *
 * Architecture: the engine is detector-agnostic. `PiiDetector` is the
 * pluggable contract; this file ships two implementations:
 *
 *  - `HeuristicPiiDetector` - static pattern rules with per-category
 *    semantic validators (Luhn for cards, SSA area rules for SSNs) so a
 *    regex hit alone is never sufficient to classify.
 *  - `EmbeddingClassifierDetector` - adapter for cognitive micro-model
 *    lookups (Llama-Guard-class classifiers). The transport is injected
 *    via `ClassifierClient`, keeping this module free of any vendor
 *    binding; wire a real client in the deployment composition root.
 *
 * Failure semantics: `PiiScanner.scan` throws `PiiScanError` if ANY
 * detector rejects. The pipeline layer decides what that means under the
 * active SECURITY_MODE (FAIL_CLOSED → block the request). The scanner
 * itself never silently degrades to partial coverage.
 */

import { SurrogateCategory, TokenVault } from '../crypto/tokenVault';

/** A single detected sensitive span, half-open interval [start, end). */
export interface PiiFinding {
  readonly category: SurrogateCategory;
  readonly start: number;
  readonly end: number;
  /** Detector self-assessed confidence in [0, 1]. */
  readonly confidence: number;
  /** Name of the detector that produced this finding. */
  readonly detector: string;
}

/** Pluggable detection contract. Implementations must be side-effect free. */
export interface PiiDetector {
  readonly name: string;
  detect(text: string): Promise<readonly PiiFinding[]>;
}

/** Result of a full scan-and-redact pass. */
export interface PiiScanResult {
  /** Input text with every accepted finding replaced by a vault surrogate. */
  readonly sanitizedText: string;
  /** Findings that were redacted, in ascending span order. */
  readonly findings: readonly PiiFinding[];
  /**
   * The exact surrogates spliced into sanitizedText. Callers use these to
   * build the per-request restoration allowlist: a response stream may
   * only resolve surrogates minted for its own request, never another
   * tenant's, regardless of what the vault globally contains.
   */
  readonly surrogates: readonly string[];
}

/** Raised when any detector fails; carries the failing detector names. */
export class PiiScanError extends Error {
  public readonly failedDetectors: readonly string[];

  public constructor(failedDetectors: readonly string[], cause?: unknown) {
    super(
      `PII scan incomplete - detector failure(s): ${failedDetectors.join(', ')}`,
    );
    this.name = 'PiiScanError';
    this.failedDetectors = failedDetectors;
    if (cause !== undefined) {
      (this as { cause?: unknown }).cause = cause;
    }
  }
}

/* -------------------------------------------------------------------------
 * Heuristic detector
 * ---------------------------------------------------------------------- */

interface HeuristicRule {
  readonly id: string;
  readonly category: SurrogateCategory;
  /** MUST carry the `g` flag; a fresh copy is taken per scan. */
  readonly pattern: RegExp;
  readonly confidence: number;
  /** Optional semantic validator applied to the raw match. */
  readonly validate?: (match: string) => boolean;
}

/** Luhn checksum - required before any digit run is classified as a card. */
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
  // Reject trivially non-card runs (all one digit) before Luhn.
  if (/^(\d)\1+$/.test(digits)) {
    return false;
  }
  return passesLuhn(digits);
}

/** SSA structural rules: area ∉ {000, 666, 900-999}, group ≠ 00, serial ≠ 0000. */
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
    // Every quantifier is bounded (RFC 5321 caps: 64-char local part,
    // 63-char labels). Unbounded local-part matching is O(n^2) over
    // attacker text and would hang the event loop on large payloads.
    category: SurrogateCategory.EMAIL,
    pattern:
      /[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24}/g,
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
    // 13-19 digits allowing single space/dash separators between groups.
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
    pattern:
      /-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----[\s\S]{1,65536}?-----END [A-Z ]{0,20}PRIVATE KEY-----/g,
    confidence: 1,
  },
];

export class HeuristicPiiDetector implements PiiDetector {
  public readonly name = 'heuristic-static';

  private readonly rules: readonly HeuristicRule[];

  public constructor(rules: readonly HeuristicRule[] = HEURISTIC_RULES) {
    for (const rule of rules) {
      if (!rule.pattern.global) {
        throw new TypeError(
          `HeuristicPiiDetector: rule "${rule.id}" pattern must use the g flag`,
        );
      }
    }
    this.rules = rules;
  }

  public detect(text: string): Promise<readonly PiiFinding[]> {
    const findings: PiiFinding[] = [];
    for (const rule of this.rules) {
      // Fresh regex per rule per scan: shared lastIndex state across
      // concurrent requests is a classic cross-request corruption bug.
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

/* -------------------------------------------------------------------------
 * Cognitive micro-model adapter
 * ---------------------------------------------------------------------- */

/** One classified span as returned by an external micro-model service. */
export interface ClassifiedSpan {
  readonly label: string;
  readonly start: number;
  readonly end: number;
  readonly score: number;
}

/**
 * Transport contract for a Llama-Guard-class classifier. Implementations
 * own batching, retries, and authentication to the model host; this module
 * only depends on the shape of the answer.
 */
export interface ClassifierClient {
  classify(text: string): Promise<readonly ClassifiedSpan[]>;
}

/** Maps micro-model labels onto vault categories; unknown labels are dropped. */
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

  public constructor(
    client: ClassifierClient,
    options: { readonly name?: string; readonly minimumScore?: number } = {},
  ) {
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
      if (
        !Number.isInteger(span.start) ||
        !Number.isInteger(span.end) ||
        span.start < 0 ||
        span.end > text.length ||
        span.start >= span.end
      ) {
        // Never trust remote span arithmetic blindly - a malformed span
        // would corrupt the redaction splice below.
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

/**
 * Inert client for deployments that have not provisioned a micro-model yet.
 * Keeps the composition root uniform: the scanner always receives the same
 * detector set; only the client binding changes per environment.
 */
export class NullClassifierClient implements ClassifierClient {
  public classify(): Promise<readonly ClassifiedSpan[]> {
    return Promise.resolve([]);
  }
}

/* -------------------------------------------------------------------------
 * Scanner engine
 * ---------------------------------------------------------------------- */

/**
 * Overlap resolution: findings sorted by start; on overlap the longer span
 * wins, ties broken by higher confidence. This keeps `sk-abc…` from being
 * split by an email match inside it, and vice versa.
 */
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
  private readonly vault: TokenVault;
  private readonly detectors: readonly PiiDetector[];

  public constructor(vault: TokenVault, detectors: readonly PiiDetector[]) {
    if (detectors.length === 0) {
      throw new RangeError('PiiScanner requires at least one detector');
    }
    this.vault = vault;
    this.detectors = detectors;
  }

  /**
   * Runs every detector, resolves overlapping findings, and splices vault
   * surrogates into the text right-to-left so earlier offsets stay valid.
   *
   * @throws PiiScanError when any detector rejects - the caller enforces
   *         SECURITY_MODE; this engine never returns partial coverage.
   */
  public async scan(text: string): Promise<PiiScanResult> {
    if (text.length === 0) {
      return { sanitizedText: text, findings: [], surrogates: [] };
    }

    const settled = await Promise.allSettled(
      this.detectors.map((detector) => detector.detect(text)),
    );

    const failed: string[] = [];
    const collected: PiiFinding[] = [];
    let firstCause: unknown;
    settled.forEach((outcome, index) => {
      const detector = this.detectors[index];
      const detectorName = detector?.name ?? `detector#${index}`;
      if (outcome.status === 'fulfilled') {
        collected.push(...outcome.value);
      } else {
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
      const surrogate = this.vault.tokenize(raw, finding.category);
      surrogates.push(surrogate);
      sanitizedText =
        sanitizedText.slice(0, finding.start) +
        surrogate +
        sanitizedText.slice(finding.end);
    }

    return { sanitizedText, findings: accepted, surrogates };
  }
}
