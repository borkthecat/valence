import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parse } from 'yaml';
import { HeuristicInjectionDetector, InjectionShield } from '../src/core/filters/injectionShield';
import { binaryMetrics } from './metrics';

interface InjectionCase {
    readonly text: string;
    readonly label: boolean;
    readonly category?: string;
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
    if (input === undefined) {
        throw new Error('usage: npm run benchmark:injection -- <pint-compatible.yaml|dataset.jsonl>');
    }
    const cases = loadCases(resolve(input));
    const shield = new InjectionShield([new HeuristicInjectionDetector()]);
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
    process.stdout.write(`${JSON.stringify({
        benchmark: 'prompt-injection',
        detector: 'valence-heuristic-injection',
        metrics: binaryMetrics(truePositive, trueNegative, falsePositive, falseNegative),
        errorsByCategory: Object.fromEntries(categoryErrors),
    }, null, 2)}\n`);
}

run().catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
