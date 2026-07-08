import { createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { HeuristicPiiDetector, type PiiFinding } from '../src/core/filters/piiScanner';

interface Entity {
    readonly start: number;
    readonly end: number;
    readonly label: string;
}

const SUPPORTED_LABELS: Readonly<Record<string, string>> = {
    EMAIL: 'EMAIL',
    EMAIL_ADDRESS: 'EMAIL',
    SSN: 'SSN',
    US_SSN: 'SSN',
    CREDIT_CARD: 'CREDIT_CARD',
    CREDITCARD: 'CREDIT_CARD',
    TEL: 'PHONE',
    PHONE: 'PHONE',
    PHONE_NUMBER: 'PHONE',
    IP: 'IP_ADDRESS',
    IP_ADDRESS: 'IP_ADDRESS',
    API_KEY: 'API_KEY',
    ACCESS_TOKEN: 'ACCESS_TOKEN',
    PASSWORD: 'PASSWORD',
};

function normalizedRecord(value: unknown): { text: string; entities: Entity[] } {
    if (typeof value !== 'object' || value === null) {
        throw new TypeError('PII benchmark record must be an object');
    }
    const record = value as Record<string, unknown>;
    const text = record.source_text ?? record.text;
    const rawEntities = record.privacy_mask ?? record.entities;
    if (typeof text !== 'string' || !Array.isArray(rawEntities)) {
        throw new TypeError('PII record needs source_text/text and privacy_mask/entities');
    }
    const entities = rawEntities.map((item) => {
        if (typeof item !== 'object' || item === null) {
            throw new TypeError('PII entity must be an object');
        }
        const entity = item as Record<string, unknown>;
        if (
            !Number.isInteger(entity.start)
            || !Number.isInteger(entity.end)
            || typeof entity.label !== 'string'
        ) {
            throw new TypeError('PII entity needs integer start/end and string label');
        }
        return {
            start: entity.start as number,
            end: entity.end as number,
            label: entity.label,
        };
    });
    return { text, entities };
}

function key(start: number, end: number, label: string): string {
    return `${start}:${end}:${label}`;
}

function findingKey(finding: PiiFinding): string {
    return key(finding.start, finding.end, finding.category);
}

async function run(): Promise<void> {
    const input = process.argv[2];
    const limitArg = process.argv[3];
    if (input === undefined) {
        throw new Error('usage: npm run benchmark:pii -- <ai4privacy-compatible.jsonl> [limit]');
    }
    const limit = limitArg === undefined ? Number.POSITIVE_INFINITY : Number(limitArg);
    if (!(limit > 0)) {
        throw new RangeError('limit must be positive');
    }
    const detector = new HeuristicPiiDetector();
    const reader = createInterface({
        input: createReadStream(resolve(input), { encoding: 'utf8' }),
        crlfDelay: Infinity,
    });
    let records = 0;
    let allGroundTruth = 0;
    let supportedGroundTruth = 0;
    let supportedTruePositive = 0;
    let supportedFalsePositive = 0;
    let supportedFalseNegative = 0;
    const perLabel = new Map<string, { truePositive: number; falsePositive: number; falseNegative: number }>();
    const supportedCategories = new Set(Object.values(SUPPORTED_LABELS));
    for await (const line of reader) {
        const normalizedLine = line.replace(/^\uFEFF/, '').trim();
        if (normalizedLine.length === 0) continue;
        const record = normalizedRecord(JSON.parse(normalizedLine));
        const findings = await detector.detect(record.text);
        const truth = new Set<string>();
        for (const entity of record.entities) {
            allGroundTruth += 1;
            const mapped = SUPPORTED_LABELS[entity.label.toUpperCase()];
            if (mapped !== undefined) {
                truth.add(key(entity.start, entity.end, mapped));
                supportedGroundTruth += 1;
            }
        }
        const predictions = new Set(findings.map(findingKey));
        for (const prediction of predictions) {
            const label = prediction.split(':', 3)[2] ?? '';
            if (!supportedCategories.has(label)) continue;
            const metrics = perLabel.get(label) ?? { truePositive: 0, falsePositive: 0, falseNegative: 0 };
            if (truth.has(prediction)) {
                supportedTruePositive += 1;
                metrics.truePositive += 1;
            } else {
                supportedFalsePositive += 1;
                metrics.falsePositive += 1;
            }
            perLabel.set(label, metrics);
        }
        for (const expected of truth) {
            if (!predictions.has(expected)) {
                supportedFalseNegative += 1;
                const label = expected.split(':', 3)[2] ?? '';
                const metrics = perLabel.get(label) ?? { truePositive: 0, falsePositive: 0, falseNegative: 0 };
                metrics.falseNegative += 1;
                perLabel.set(label, metrics);
            }
        }
        records += 1;
        if (records >= limit) break;
    }
    const precisionDenominator = supportedTruePositive + supportedFalsePositive;
    const recallDenominator = supportedTruePositive + supportedFalseNegative;
    const precision = precisionDenominator === 0 ? 0 : supportedTruePositive / precisionDenominator;
    const recall = recallDenominator === 0 ? 0 : supportedTruePositive / recallDenominator;
    process.stdout.write(`${JSON.stringify({
        benchmark: 'pii-span-detection',
        detector: 'valence-heuristic-static',
        records,
        allGroundTruthEntities: allGroundTruth,
        supportedGroundTruthEntities: supportedGroundTruth,
        labelCoverage: allGroundTruth === 0 ? 0 : supportedGroundTruth / allGroundTruth,
        exactSpanMetricsOnSupportedLabels: {
            truePositive: supportedTruePositive,
            falsePositive: supportedFalsePositive,
            falseNegative: supportedFalseNegative,
            precision,
            recall,
            f1: precision + recall === 0 ? 0 : 2 * precision * recall / (precision + recall),
        },
        perLabel: Object.fromEntries(
            [...perLabel.entries()].map(([label, metrics]) => {
                const labelPrecision = metrics.truePositive + metrics.falsePositive === 0
                    ? 0
                    : metrics.truePositive / (metrics.truePositive + metrics.falsePositive);
                const labelRecall = metrics.truePositive + metrics.falseNegative === 0
                    ? 0
                    : metrics.truePositive / (metrics.truePositive + metrics.falseNegative);
                return [label, {
                    ...metrics,
                    precision: labelPrecision,
                    recall: labelRecall,
                    f1: labelPrecision + labelRecall === 0
                        ? 0
                        : 2 * labelPrecision * labelRecall / (labelPrecision + labelRecall),
                }];
            }),
        ),
    }, null, 2)}\n`);
}

run().catch((error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
});
