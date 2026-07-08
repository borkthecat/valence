import assert from 'node:assert/strict';
import { createClient } from 'redis';
import { RedisTokenVault, SurrogateCategory } from '../src/core/crypto/tokenVault';

async function run(): Promise<void> {
    const redisUrl = process.env.REDIS_URL ?? 'redis://localhost:6379';
    const prefix = `valence:test:${Date.now()}:${Math.random().toString(16).slice(2)}`;
    const key = 'redis-vault-test-key-material-0123456789abcdef';
    const vault = new RedisTokenVault(redisUrl, key, prefix);
    const client = createClient({ url: redisUrl });
    await client.connect();
    try {
        const first = await vault.tokenize('redis-user@example.com', SurrogateCategory.EMAIL);
        const second = await vault.tokenize('redis-user@example.com', SurrogateCategory.EMAIL);
        assert.equal(second, first, 'repeat tokenization remains stable');
        assert.equal(await vault.detokenize(first), 'redis-user@example.com', 'redis round trip');
        assert.equal(await vault.restoreText(`mail ${first}`), 'mail redis-user@example.com', 'redis restore');
        const keys: string[] = [];
        for await (const keyName of client.scanIterator({ MATCH: `${prefix}:*`, COUNT: 100 })) {
            if (Array.isArray(keyName)) {
                keys.push(...keyName);
            }
            else {
                keys.push(keyName);
            }
        }
        assert.ok(keys.length >= 2, 'forward and reverse keys exist');
        assert.ok(keys.every((keyName) => !keyName.includes('redis-user@example.com')), 'raw value is not present in key names');
        assert.equal(await vault.revoke(first), true, 'redis revoke succeeds');
        assert.equal(await vault.detokenize(first), null, 'revoked redis surrogate resolves to null');
    }
    finally {
        await vault.clearAll();
        await vault.disconnect();
        await client.quit();
    }
    console.log('redis-vault.smoke: OK');
}

run().catch((error) => {
    console.error('redis-vault.smoke: FAILED', error);
    process.exit(1);
});
