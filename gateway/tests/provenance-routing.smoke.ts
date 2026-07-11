import { strict as assert } from 'node:assert';
import { GuardModelDetector, InjectionShield, type GuardModelClient } from '../src/core/filters/injectionShield';
import { routeForProvenance } from '../src/core/filters/provenanceRouting';
import { decideGuardRoute } from '../src/core/filters/expertRouting';

async function run(): Promise<void> {
    const article = routeForProvenance({ boundary: 'compiled_article' });
    const source = routeForProvenance({ boundary: 'raw_source' });
    const contestedSource = routeForProvenance({ boundary: 'raw_source', contentionScore: 0.8 });
    const secret = routeForProvenance({ boundary: 'secret_store' });

    assert.equal(article.policy, 'direct');
    assert.equal(article.minimumModelScore, 0.85);
    assert.equal(source.policy, 'indirect');
    assert.equal(source.minimumModelScore, 0.35);
    assert.equal(contestedSource.minimumModelScore, 0.25);
    assert.equal(secret.policy, 'secret');

    const experts = new Set(['cgoosen_combined', 'hse_llm', 'smooth_3']);
    const review = new Set(['cgoosen_combined', 'hse_llm']);
    assert.deepEqual(decideGuardRoute({ sourceId: 'cgoosen_combined' }, experts, review), {
        route: 'source-expert',
        action: 'review',
    });
    assert.deepEqual(decideGuardRoute({ sourceId: 'smooth_3' }, experts, review), {
        route: 'source-expert',
        action: 'enforce',
    });
    assert.deepEqual(decideGuardRoute({ sourceId: 'wambosec' }, experts, review), {
        route: 'global-v6',
        action: 'enforce',
    });

    const guard: GuardModelClient = {
        assess: async () => ({ label: 'prompt_injection', score: 0.5 }),
    };
    const shield = new InjectionShield([new GuardModelDetector(guard)]);

    assert.equal((await shield.evaluate('quoted trigger', article)).blocked, false);
    assert.equal((await shield.evaluate('untrusted trigger', source)).blocked, true);

    process.stdout.write('provenance-routing.smoke: OK\n');
}

run().catch((error) => {
    console.error('provenance-routing.smoke: FAILED', error);
    process.exit(1);
});
