import { randomBytes } from 'node:crypto';
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
    GENERIC_SECRET = 'GENERIC_SECRET'
}
export const VAULT_ENTRY_TTL_MS = 5 * 60 * 1000;
const SURROGATE_ENTROPY_BYTES = 8;
export const SURROGATE_PATTERN = /\[M_[A-Z_]{1,32}_[0-9a-f]{16}\]/g;
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
function forwardKey(category: SurrogateCategory, raw: string): string {
    return `${category}\u{001F}${raw}`;
}
export class TokenVault {
    private static instance: TokenVault | null = null;
    private readonly rawToEntry = new Map<string, VaultEntry>();
    private readonly surrogateToEntry = new Map<string, VaultEntry>();
    private evictionCount = 0;
    private tokenizationCount = 0;
    private constructor() {
    }
    public static getInstance(): TokenVault {
        if (TokenVault.instance === null) {
            TokenVault.instance = new TokenVault();
        }
        return TokenVault.instance;
    }
    public static resetInstance(): void {
        if (TokenVault.instance !== null) {
            TokenVault.instance.clearAll();
            TokenVault.instance = null;
        }
    }
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
    public detokenize(surrogate: string): string | null {
        const entry = this.surrogateToEntry.get(surrogate);
        if (entry === undefined) {
            return null;
        }
        if (Date.now() >= entry.expiresAt) {
            this.evict(entry.surrogate);
            return null;
        }
        return entry.raw;
    }
    public restoreText(text: string): string {
        return text.replace(SURROGATE_PATTERN, (marker) => {
            const raw = this.detokenize(marker);
            return raw ?? marker;
        });
    }
    public revoke(surrogate: string): boolean {
        return this.evict(surrogate);
    }
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
export const tokenVault: TokenVault = TokenVault.getInstance();
