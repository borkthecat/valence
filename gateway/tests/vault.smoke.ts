import assert from 'node:assert/strict';
import { TokenVault, SurrogateCategory, VAULT_ENTRY_TTL_MS, } from '../src/core/crypto/tokenVault';
async function run(): Promise<void> {
    const vault = TokenVault.getInstance();
    const first = await vault.tokenize('alice@example.com', SurrogateCategory.EMAIL);
    const second = await vault.tokenize('alice@example.com', SurrogateCategory.EMAIL);
    assert.equal(first, second, 'repeat tokenization must be stable within TTL');
    assert.match(first, /^\[M_EMAIL_[0-9a-f]{16}\]$/, 'surrogate format');
    assert.equal(await vault.detokenize(first), 'alice@example.com', 'round trip');
    const restored = await vault.restoreText(`Contact ${first} now, ignore [M_EMAIL_deadbeefdeadbeef]`);
    assert.equal(restored, 'Contact alice@example.com now, ignore [M_EMAIL_deadbeefdeadbeef]', 'unknown surrogates left verbatim');
    const asPassword = await vault.tokenize('root', SurrogateCategory.PASSWORD);
    const asName = await vault.tokenize('root', SurrogateCategory.PERSON_NAME);
    assert.notEqual(asPassword, asName, 'same value in two categories stays distinct');
    assert.equal(await vault.revoke(first), true, 'revoke succeeds');
    assert.equal(await vault.detokenize(first), null, 'revoked surrogate resolves to null');
    assert.equal(VAULT_ENTRY_TTL_MS, 5 * 60 * 1000, 'TTL is 5 minutes');
    TokenVault.resetInstance();
    console.log('vault.smoke: OK');
}
run().catch((error) => {
    console.error('vault.smoke: FAILED', error);
    process.exit(1);
});
