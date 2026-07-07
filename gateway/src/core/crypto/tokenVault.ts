/**
 * Valence Gateway - Cryptographic Token Vault
 *
 * In-memory, bidirectional tokenization store used by the DLP redaction
 * layer. Sensitive values detected in outbound prompts (emails, phone
 * numbers, API keys, …) are swapped for opaque surrogates such as
 * `[M_EMAIL_9f2c41d0a7b3e815]` before the request leaves the trust
 * boundary; when the upstream response returns, surrogates are swapped
 * back so the client sees the original data.
 *
 * Design constraints:
 *  - Surrogates carry zero information about the raw value: 64 bits of
 *    CSPRNG entropy from `crypto.randomBytes`, never a hash of the input.
 *  - Every entry has a hard 5-minute TTL enforced with a dedicated
 *    `setTimeout` handle (cleared and re-armed on refresh) so the heap
 *    cannot grow unboundedly under sustained traffic.
 *  - Timers are `unref()`ed so a populated vault never prevents a clean
 *    process shutdown.
 *  - The vault is a process-wide Singleton: the request-scanning and
 *    response-restoring middleware must observe the same state.
 */

import { randomBytes } from 'node:crypto';

/** Classification of the sensitive value a surrogate stands in for. */
export enum SurrogateCategory {
  EMAIL = 'EMAIL',
  PHONE = 'PHONE',
  SSN = 'SSN',
  CREDIT_CARD = 'CREDIT_CARD',
  IP_ADDRESS = 'IP_ADDRESS',
  API_KEY = 'API_KEY',
  ACCESS_TOKEN = 'ACCESS_TOKEN',
  PASSWORD = 'PASSWORD',
  PERSON_NAME = 'PERSON_NAME',
  GENERIC_SECRET = 'GENERIC_SECRET',
}

/** Hard eviction deadline for every vault entry: 5 minutes. */
export const VAULT_ENTRY_TTL_MS = 5 * 60 * 1_000;

/** Hex characters appended to the surrogate marker (8 random bytes). */
const SURROGATE_ENTROPY_BYTES = 8;

/**
 * Matches any surrogate this vault can emit, e.g. `[M_EMAIL_9f2c41d0a7b3e815]`.
 * Used by `restoreText` to rewrite upstream responses in a single pass.
 * The category class is bounded at 32 chars (matching the reconstructor's
 * MAX_SURROGATE_LENGTH budget) so adversarial text full of `[M_` prefixes
 * cannot induce unbounded backtracking.
 */
export const SURROGATE_PATTERN =
  /\[M_[A-Z_]{1,32}_[0-9a-f]{16}\]/g;

interface VaultEntry {
  readonly raw: string;
  readonly surrogate: string;
  readonly category: SurrogateCategory;
  readonly createdAt: number;
  expiresAt: number;
  timer: NodeJS.Timeout;
}

export interface VaultStats {
  readonly size: number;
  readonly evictions: number;
  readonly tokenizations: number;
}

/**
 * `Map` keys must disambiguate identical raw strings across categories
 * (the literal "root" as a PERSON_NAME is a different secret than "root"
 * as a PASSWORD). The ASCII unit separator (0x1F) cannot appear in the
 * category enum, so the composite key is collision-free.
 */
function forwardKey(category: SurrogateCategory, raw: string): string {
  return `${category}\u{001F}${raw}`;
}

export class TokenVault {
  private static instance: TokenVault | null = null;

  /** category+raw → entry (dedup: same value re-tokenizes to same surrogate). */
  private readonly rawToEntry = new Map<string, VaultEntry>();

  /** surrogate → entry (restoration path). */
  private readonly surrogateToEntry = new Map<string, VaultEntry>();

  private evictionCount = 0;
  private tokenizationCount = 0;

  private constructor() {
    // Singleton: construction only via getInstance().
  }

  public static getInstance(): TokenVault {
    if (TokenVault.instance === null) {
      TokenVault.instance = new TokenVault();
    }
    return TokenVault.instance;
  }

  /**
   * Destroys the singleton, clearing all entries and timers. Intended for
   * test isolation and coordinated shutdown; a subsequent getInstance()
   * yields a fresh, empty vault.
   */
  public static resetInstance(): void {
    if (TokenVault.instance !== null) {
      TokenVault.instance.clearAll();
      TokenVault.instance = null;
    }
  }

  /**
   * Exchanges a raw sensitive value for a surrogate marker.
   *
   * Idempotent within the TTL window: tokenizing the same (category, raw)
   * pair returns the existing surrogate and re-arms its eviction timer,
   * so a value that keeps appearing in live traffic keeps a stable alias
   * while idle values still age out on schedule.
   */
  public tokenize(raw: string, category: SurrogateCategory): string {
    if (raw.length === 0) {
      throw new RangeError('TokenVault.tokenize: raw value must be non-empty');
    }

    const key = forwardKey(category, raw);
    const existing = this.rawToEntry.get(key);
    if (existing !== undefined) {
      this.refreshTtl(existing);
      return existing.surrogate;
    }

    const surrogate = this.generateSurrogate(category);
    const now = Date.now();
    const entry: VaultEntry = {
      raw,
      surrogate,
      category,
      createdAt: now,
      expiresAt: now + VAULT_ENTRY_TTL_MS,
      timer: this.armEvictionTimer(surrogate),
    };

    this.rawToEntry.set(key, entry);
    this.surrogateToEntry.set(surrogate, entry);
    this.tokenizationCount += 1;
    return surrogate;
  }

  /**
   * Resolves a surrogate back to its raw value, or `null` when the
   * surrogate is unknown or already evicted. Callers operating under
   * FAIL_CLOSED must treat `null` as a hard error, never as empty string.
   */
  public detokenize(surrogate: string): string | null {
    const entry = this.surrogateToEntry.get(surrogate);
    if (entry === undefined) {
      return null;
    }
    // Defense in depth: if the event loop was blocked past the deadline,
    // honour the TTL logically even though the timer has not fired yet.
    if (Date.now() >= entry.expiresAt) {
      this.evict(entry.surrogate);
      return null;
    }
    return entry.raw;
  }

  /**
   * Rewrites every known surrogate in `text` back to its raw value in a
   * single scan. Unknown or expired surrogates are left verbatim so the
   * caller can detect and act on unresolved markers.
   */
  public restoreText(text: string): string {
    return text.replace(SURROGATE_PATTERN, (marker) => {
      const raw = this.detokenize(marker);
      return raw ?? marker;
    });
  }

  /** Immediately and permanently removes one surrogate. */
  public revoke(surrogate: string): boolean {
    return this.evict(surrogate);
  }

  /** Removes every entry and cancels every pending eviction timer. */
  public clearAll(): void {
    for (const entry of this.surrogateToEntry.values()) {
      clearTimeout(entry.timer);
    }
    this.surrogateToEntry.clear();
    this.rawToEntry.clear();
  }

  public get stats(): VaultStats {
    return Object.freeze({
      size: this.surrogateToEntry.size,
      evictions: this.evictionCount,
      tokenizations: this.tokenizationCount,
    });
  }

  private generateSurrogate(category: SurrogateCategory): string {
    // 64 bits of entropy makes collisions vanishingly unlikely, but the
    // vault is authoritative state - loop until provably unique anyway.
    for (;;) {
      const entropy = randomBytes(SURROGATE_ENTROPY_BYTES).toString('hex');
      const surrogate = `[M_${category}_${entropy}]`;
      if (!this.surrogateToEntry.has(surrogate)) {
        return surrogate;
      }
    }
  }

  private armEvictionTimer(surrogate: string): NodeJS.Timeout {
    const timer = setTimeout(() => {
      this.evict(surrogate);
    }, VAULT_ENTRY_TTL_MS);
    // A populated vault must never keep the process alive on shutdown.
    timer.unref();
    return timer;
  }

  private refreshTtl(entry: VaultEntry): void {
    clearTimeout(entry.timer);
    entry.expiresAt = Date.now() + VAULT_ENTRY_TTL_MS;
    entry.timer = this.armEvictionTimer(entry.surrogate);
  }

  private evict(surrogate: string): boolean {
    const entry = this.surrogateToEntry.get(surrogate);
    if (entry === undefined) {
      return false;
    }
    clearTimeout(entry.timer);
    this.surrogateToEntry.delete(surrogate);
    this.rawToEntry.delete(forwardKey(entry.category, entry.raw));
    this.evictionCount += 1;
    return true;
  }
}

/** Convenience accessor for the process-wide vault. */
export const tokenVault: TokenVault = TokenVault.getInstance();
