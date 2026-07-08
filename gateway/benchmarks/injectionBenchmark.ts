import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';
import { GuardModelDetector, HeuristicInjectionDetector, InjectionShield } from '../src/core/filters/injectionShield';
import { LocalGuardModelClient } from '../src/services/modelClients';
import { binaryMetrics } from './metrics';

interface InjectionCase {
    readonly text: string;
    readonly label: boolean;
    readonly category?: string;
}

function wilsonInterval(successes: number, total: number): { lower: number; upper: number } {
    if (total === 0) return { lower: 0, upper: 0 };
    const z = 1.959963984540054;
    const observed = successes / total;
    const denominator = 1 + (z * z) / total;
    const center = (observed + (z * z) / (2 * total)) / denominator;
    const margin = z * Math.sqrt(
        (observed * (1 - observed)) / total + (z * z) / (4 * total * total),
    ) / denominator;
    return { lower: center - margin, upper: center + margin };
}

function loadCases(path: string): InjectionCase[] {
    const raw = readFileSync(path, 'utf8');
    const parsed = path.endsWith('.jsonl')
        ? raw.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
        : parse(raw);
    if (!Array.isArray(parsed)) {
        throw new TypeError('benchmark dataset must be a YAML array or JSONL records');
    }
    return parsed.map((item, index) => {
        if (
            typeof item !== 'object'
            || item === null
            || typeof item.text !== 'string'
            || typeof item.label !== 'boolean'
        ) {
            throw new TypeError(`invalid injection benchmark record at index ${index}`);
        }
        return {
            text: item.text,
            label: item.label,
            ...(typeof item.category === 'string' ? { category: item.category } : {}),
        };
    });
}

async function run(): Promise<void> {
    const input = process.argv[2];
    const modelPath = process.argv[3];
    const minimumF1 = process.argv[4] === undefined ? undefined : Number(process.argv[4]);
    const minimumAccuracyLowerBound = process.argv[5] === undefined ? undefined : Number(process.argv[5]);
    if (input === undefined) {
        throw new Error('usage: npm run benchmark:injection -- <pint-compatible.yaml|dataset.jsonl> [guard-model.json]');
    }
    const cases = loadCases(resolve(input));
    const shield = new InjectionShield([
        new HeuristicInjectionDetector(),
        ...(modelPath === undefined
            ? []
            : [new GuardModelDetector(new LocalGuardModelClient(resolve(modelPath)))]),
    ]);
    let truePositive = 0;
    let trueNegative = 0;
    let falsePositive = 0;
    let falseNegative = 0;
    const categoryErrors = new Map<string, { falsePositive: number; falseNegative: number }>();
    for (const item of cases) {
        const predicted = (await shield.evaluate(item.text)).blocked;
        if (predicted && item.label) truePositive += 1;
        else if (!predicted && !item.label) trueNegative += 1;
        else if (predicted) falsePositive += 1;
        else falseNegative += 1;
        if (predicted !== item.label) {
            const category = item.category ?? 'uncategorized';
            const current = categoryErrors.get(category) ?? { falsePositive: 0, falseNegative: 0 };
            if (predicted) current.falsePositive += 1;
            else current.falseNegative += 1;
            categoryErrors.set(category, current);
        }
    }
    const metrics = binaryMetrics(truePositive, trueNegative, falsePositive, falseNegative);
    const accuracy95ConfidenceInterval = wilsonInterval(
        metrics.truePositive + metrics.trueNegative,
        metrics.samples,
    );
    process.stdout.write(`${JSON.stringify({
        benchmark: 'prompt-injection',
        detector: modelPath === undefined ? 'valence-heuristic-injection' : 'valence-heuristic-plus-local-guard',
        metrics,
        accuracy95ConfidenceInterval,
        errorsByCategory: Object.fromEntries(categoryErrors),
    }, null, 2)}\n`);
    if (minimumF1 !== undefined && (!Number.isFinite(minimumF1) || metrics.f1 < minimumF1)) {
        process.exitCode = 2;
    }
    if (
        minimumAccuracyLowerBound !== undefined
        && (!Number.isFinite(minimumAccuracyLowerBound)
            || accuracy95ConfidenceInterval.lower < minimumAccuracyLowerBound)
    ) {
        process.exitCode = 2;
    }
}

run().catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
