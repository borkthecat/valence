import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { performance } from 'node:perf_hooks';
import pino from 'pino';
import { percentile } from './metrics';

const GATEWAY_KEY = 'benchmark-gateway-key-0123456789abcdef';

async function listen(server: ReturnType<typeof createServer>): Promise<number> {
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    return (server.address() as AddressInfo).port;
}

async function close(server: ReturnType<typeof createServer>): Promise<void> {
    await new Promise<void>((resolve, reject) => {
        server.close((error) => error === undefined ? resolve() : reject(error));
    });
}

async function measure(
    url: string,
    iterations: number,
    concurrency: number,
    protectedRoute: boolean,
): Promise<{ durationMs: number; samples: number[] }> {
    const samples: number[] = [];
    let cursor = 0;
    const started = performance.now();
    async function worker(): Promise<void> {
        while (true) {
            const index = cursor;
            cursor += 1;
            if (index >= iterations) return;
            const itemStarted = performance.now();
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'content-type': 'application/json',
                    ...(protectedRoute ? { 'x-valence-key': GATEWAY_KEY } : {}),
                },
                body: JSON.stringify({
                    model: 'benchmark',
                    messages: [{
                        role: 'user',
                        content: `Summarize account ${index} for user${index}@example.com.`,
                    }],
                }),
            });
            if (!response.ok) {
                throw new Error(`benchmark request failed with ${response.status}`);
            }
            await response.arrayBuffer();
            samples.push(performance.now() - itemStarted);
        }
    }
    await Promise.all(Array.from({ length: concurrency }, () => worker()));
    return { durationMs: performance.now() - started, samples };
}

function summarize(result: { durationMs: number; samples: number[] }): Record<string, number> {
    result.samples.sort((a, b) => a - b);
    return {
        throughputPerSecond: result.samples.length / (result.durationMs / 1000),
        p50: percentile(result.samples, 0.50),
        p95: percentile(result.samples, 0.95),
        p99: percentile(result.samples, 0.99),
        max: result.samples[result.samples.length - 1] ?? 0,
    };
}

async function run(): Promise<void> {
    const iterations = Number(process.argv[2] ?? 1000);
    const concurrency = Number(process.argv[3] ?? 20);
    if (!Number.isInteger(iterations) || iterations < 1 || !Number.isInteger(concurrency) || concurrency < 1) {
        throw new RangeError('usage: npm run benchmark:http -- [positive iterations] [positive concurrency]');
    }
    const upstream = createServer((request, response) => {
        const chunks: Buffer[] = [];
        request.on('data', (chunk: Buffer) => chunks.push(chunk));
        request.on('end', () => {
            response.writeHead(200, { 'content-type': 'application/json' });
            response.end(Buffer.concat(chunks));
        });
    });
    const upstreamPort = await listen(upstream);
    process.env.PORT = '18443';
    process.env.UPSTREAM_PROVIDER_URL = `http://127.0.0.1:${upstreamPort}`;
    process.env.UPSTREAM_API_KEY = 'benchmark-provider-key';
    process.env.GATEWAY_API_KEY = GATEWAY_KEY;
    process.env.SECURITY_MODE = 'FAIL_CLOSED';
    process.env.AUTH_MODE = 'api_key';
    process.env.AUDIT_LOG_PATH = 'off';
    process.env.RATE_LIMIT_MAX_REQUESTS = '100000';
    process.env.NODE_ENV = 'test';
    const appModule = await import('../src/app');
    const gateway = createServer(appModule.buildApp(pino({ level: 'silent' })));
    const gatewayPort = await listen(gateway);
    try {
        const direct = await measure(
            `http://127.0.0.1:${upstreamPort}/v1/messages`,
            iterations,
            concurrency,
            false,
        );
        const protectedResult = await measure(
            `http://127.0.0.1:${gatewayPort}/v1/messages`,
            iterations,
            concurrency,
            true,
        );
        const directSummary = summarize(direct);
        const protectedSummary = summarize(protectedResult);
        process.stdout.write(`${JSON.stringify({
            benchmark: 'gateway-http-overhead',
            iterations,
            concurrency,
            directUpstream: directSummary,
            protectedGateway: protectedSummary,
            addedLatencyMs: {
                p50: protectedSummary.p50 - directSummary.p50,
                p95: protectedSummary.p95 - directSummary.p95,
                p99: protectedSummary.p99 - directSummary.p99,
            },
            scope: 'local loopback HTTP with stub upstream; includes auth, request parsing, injection screening, PII tokenization, proxying, and response restoration',
        }, null, 2)}\n`);
    } finally {
        await close(gateway);
        await close(upstream);
        await appModule.shutdownGatewayResources();
    }
}

run().catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
