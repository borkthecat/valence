import { createHmac, randomBytes } from 'node:crypto';
import { createClient, type RedisClientType } from 'redis';
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

interface RedisVaultEntry {
    readonly raw: string;
    readonly surrogate: string;
    readonly category: SurrogateCategory;
    readonly createdAt: number;
}

export interface VaultStats {
    readonly size: number;
    readonly evictions: number;
    readonly tokenizations: number;
}

export interface TokenVaultBackend {
    tokenize(raw: string, category: SurrogateCategory): string | Promise<string>;
    detokenize(surrogate: string): string | null | Promise<string | null>;
    restoreText(text: string): string | Promise<string>;
    revoke(surrogate: string): boolean | Promise<boolean>;
    clearAll(): void | Promise<void>;
    readonly stats: VaultStats;
}

function forwardKey(category: SurrogateCategory, raw: string): string {
    return `${category}\u{001F}${raw}`;
}

export class TokenVault implements TokenVaultBackend {
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

export class RedisTokenVault implements TokenVaultBackend {
    private readonly client: RedisClientType;
    private readonly hmacKey: Buffer;
    private readonly prefix: string;
    private connectPromise: Promise<void> | null = null;
    private evictionCount = 0;
    private tokenizationCount = 0;

    public constructor(redisUrl: string, hmacKey: string, prefix = 'valence:vault') {
        if (hmacKey.length < 32) {
            throw new RangeError('RedisTokenVault requires at least 32 bytes of key material');
        }
        this.client = createClient({ url: redisUrl });
        this.hmacKey = Buffer.from(hmacKey, 'utf8');
        this.prefix = prefix;
    }

    public async tokenize(raw: string, category: SurrogateCategory): Promise<string> {
        if (raw.length === 0) {
            throw new RangeError('RedisTokenVault.tokenize: raw value must be non-empty');
        }
        await this.connect();
        const forward = this.forwardRedisKey(category, raw);
        const existing = await this.client.get(forward);
        if (existing !== null) {
            await Promise.all([
                this.client.pExpire(forward, VAULT_ENTRY_TTL_MS),
                this.client.pExpire(this.reverseRedisKey(existing), VAULT_ENTRY_TTL_MS),
            ]);
            return existing;
        }
        for (;;) {
            const surrogate = this.generateSurrogate(category);
            const now = Date.now();
            const entry: RedisVaultEntry = { raw, surrogate, category, createdAt: now };
            const reverse = this.reverseRedisKey(surrogate);
            const reverseSet = await this.client.set(reverse, JSON.stringify(entry), {
                PX: VAULT_ENTRY_TTL_MS,
                NX: true,
            });
            if (reverseSet !== 'OK') {
                continue;
            }
            const forwardSet = await this.client.set(forward, surrogate, {
                PX: VAULT_ENTRY_TTL_MS,
                NX: true,
            });
            if (forwardSet === 'OK') {
                this.tokenizationCount += 1;
                return surrogate;
            }
            await this.client.del(reverse);
            const winner = await this.client.get(forward);
            if (winner !== null) {
                await this.client.pExpire(this.reverseRedisKey(winner), VAULT_ENTRY_TTL_MS);
                return winner;
            }
        }
    }

    public async detokenize(surrogate: string): Promise<string | null> {
        await this.connect();
        const value = await this.client.get(this.reverseRedisKey(surrogate));
        if (value === null) {
            return null;
        }
        try {
            const entry = JSON.parse(value) as RedisVaultEntry;
            if (entry.surrogate !== surrogate || typeof entry.raw !== 'string') {
                return null;
            }
            return entry.raw;
        }
        catch {
            await this.client.del(this.reverseRedisKey(surrogate));
            return null;
        }
    }

    public async restoreText(text: string): Promise<string> {
        const pattern = new RegExp(SURROGATE_PATTERN.source, SURROGATE_PATTERN.flags);
        const markers = [...new Set(text.match(pattern) ?? [])];
        if (markers.length === 0) {
            return text;
        }
        const restored = new Map<string, string>();
        await Promise.all(markers.map(async (marker) => {
            const raw = await this.detokenize(marker);
            if (raw !== null) {
                restored.set(marker, raw);
            }
        }));
        return text.replace(pattern, (marker) => restored.get(marker) ?? marker);
    }

    public async revoke(surrogate: string): Promise<boolean> {
        await this.connect();
        const reverse = this.reverseRedisKey(surrogate);
        const value = await this.client.get(reverse);
        if (value === null) {
            return false;
        }
        let forward: string | null = null;
        try {
            const entry = JSON.parse(value) as RedisVaultEntry;
            forward = this.forwardRedisKey(entry.category, entry.raw);
        }
        catch {
            forward = null;
        }
        const deleted = forward === null
            ? await this.client.del(reverse)
            : await this.client.del([reverse, forward]);
        if (deleted > 0) {
            this.evictionCount += 1;
        }
        return deleted > 0;
    }

    public async clearAll(): Promise<void> {
        await this.connect();
        const keys: string[] = [];
        for await (const key of this.client.scanIterator({ MATCH: `${this.prefix}:*`, COUNT: 100 })) {
            if (Array.isArray(key)) {
                keys.push(...key);
            }
            else {
                keys.push(key);
            }
            if (keys.length >= 500) {
                await this.client.del(keys.splice(0, keys.length));
            }
        }
        if (keys.length > 0) {
            await this.client.del(keys);
        }
    }

    public async disconnect(): Promise<void> {
        if (this.client.isOpen) {
            await this.client.quit();
        }
        this.connectPromise = null;
    }

    public get stats(): VaultStats {
        return Object.freeze({
            size: 0,
            evictions: this.evictionCount,
            tokenizations: this.tokenizationCount,
        });
    }

    private async connect(): Promise<void> {
        if (this.client.isOpen) {
            return;
        }
        this.connectPromise ??= this.client.connect().then(() => undefined);
        await this.connectPromise;
    }

    private forwardRedisKey(category: SurrogateCategory, raw: string): string {
        const digest = createHmac('sha256', this.hmacKey)
            .update(forwardKey(category, raw), 'utf8')
            .digest('hex');
        return `${this.prefix}:forward:${digest}`;
    }

    private reverseRedisKey(surrogate: string): string {
        return `${this.prefix}:reverse:${surrogate}`;
    }

    private generateSurrogate(category: SurrogateCategory): string {
        const entropy = randomBytes(SURROGATE_ENTROPY_BYTES).toString('hex');
        return `[M_${category}_${entropy}]`;
    }
}
