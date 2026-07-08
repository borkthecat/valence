export interface BinaryMetrics {
    readonly samples: number;
    readonly truePositive: number;
    readonly trueNegative: number;
    readonly falsePositive: number;
    readonly falseNegative: number;
    readonly accuracy: number;
    readonly precision: number;
    readonly recall: number;
    readonly f1: number;
    readonly falsePositiveRate: number;
}

function ratio(numerator: number, denominator: number): number {
    return denominator === 0 ? 0 : numerator / denominator;
}

export function binaryMetrics(
    truePositive: number,
    trueNegative: number,
    falsePositive: number,
    falseNegative: number,
): BinaryMetrics {
    const precision = ratio(truePositive, truePositive + falsePositive);
    const recall = ratio(truePositive, truePositive + falseNegative);
    return {
        samples: truePositive + trueNegative + falsePositive + falseNegative,
        truePositive,
        trueNegative,
        falsePositive,
        falseNegative,
        accuracy: ratio(truePositive + trueNegative, truePositive + trueNegative + falsePositive + falseNegative),
        precision,
        recall,
        f1: ratio(2 * precision * recall, precision + recall),
        falsePositiveRate: ratio(falsePositive, falsePositive + trueNegative),
    };
}

export function percentile(sortedValues: readonly number[], percentileValue: number): number {
    if (sortedValues.length === 0) {
        return 0;
    }
    const index = Math.min(
        sortedValues.length - 1,
        Math.max(0, Math.ceil(percentileValue * sortedValues.length) - 1),
    );
    return sortedValues[index] ?? 0;
}
