import { performance } from 'node:perf_hooks';
import { TokenVault } from '../src/core/crypto/tokenVault';
import { HeuristicPiiDetector, PiiScanner } from '../src/core/filters/piiScanner';
import { HeuristicInjectionDetector, InjectionShield } from '../src/core/filters/injectionShield';
import { percentile } from './metrics';

async function run(): Promise<void> {
    const iterations = Number(process.argv[2] ?? 2000);
    const concurrency = Number(process.argv[3] ?? 20);
    if (!Number.isInteger(iterations) || iterations < 1 || !Number.isInteger(concurrency) || concurrency < 1) {
        throw new RangeError('usage: npm run benchmark:latency -- [positive iterations] [positive concurrency]');
    }
    const vault = TokenVault.getInstance();
    const scanner = new PiiScanner(vault, [new HeuristicPiiDetector()]);
    const shield = new InjectionShield([new HeuristicInjectionDetector()]);
    const samples: number[] = [];
    let cursor = 0;
    const started = performance.now();
    async function worker(): Promise<void> {
        while (true) {
            const index = cursor;
            cursor += 1;
            if (index >= iterations) return;
            const text = `Summarize order ${index} for customer user${index}@example.com without exposing payment data.`;
            const itemStarted = performance.now();
            const verdict = await shield.evaluate(text);
            if (verdict.blocked) throw new Error('benign latency fixture was blocked');
            const result = await scanner.scan(text);
            await vault.restoreText(result.sanitizedText);
            samples.push(performance.now() - itemStarted);
        }
    }
    await Promise.all(Array.from({ length: concurrency }, () => worker()));
    const durationMs = performance.now() - started;
    samples.sort((a, b) => a - b);
    process.stdout.write(`${JSON.stringify({
        benchmark: 'gateway-security-path-in-process',
        iterations,
        concurrency,
        throughputPerSecond: iterations / (durationMs / 1000),
        durationMs,
        latencyMs: {
            p50: percentile(samples, 0.50),
            p95: percentile(samples, 0.95),
            p99: percentile(samples, 0.99),
            max: samples[samples.length - 1] ?? 0,
        },
        scope: 'heuristic injection evaluation + PII detection/tokenization + restoration; excludes HTTP and upstream provider latency',
    }, null, 2)}\n`);
    TokenVault.resetInstance();
}

run().catch((error: unknown) => {
    TokenVault.resetInstance();
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
