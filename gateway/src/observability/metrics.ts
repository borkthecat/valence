export type Labels = Readonly<Record<string, string>>;
const LABEL_NAME_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
function escapeLabelValue(value: string): string {
    return value.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/"/g, '\\"');
}
function serializeLabels(labels: Labels): string {
    const keys = Object.keys(labels).sort();
    if (keys.length === 0) {
        return '';
    }
    for (const key of keys) {
        if (!LABEL_NAME_PATTERN.test(key)) {
            throw new Error(`invalid Prometheus label name: ${key}`);
        }
    }
    const parts = keys.map((key) => `${key}="${escapeLabelValue(labels[key] ?? '')}"`);
    return `{${parts.join(',')}}`;
}
interface Metric {
    readonly name: string;
    readonly help: string;
    readonly type: 'counter' | 'gauge' | 'histogram';
    collect(): string[];
}
export class Counter implements Metric {
    public readonly type = 'counter';
    private readonly values = new Map<string, number>();
    public constructor(public readonly name: string, public readonly help: string) { }
    public inc(labels: Labels = {}, amount = 1): void {
        const key = serializeLabels(labels);
        this.values.set(key, (this.values.get(key) ?? 0) + amount);
    }
    public collect(): string[] {
        if (this.values.size === 0) {
            return [`${this.name} 0`];
        }
        const lines: string[] = [];
        for (const [key, value] of this.values) {
            lines.push(`${this.name}${key} ${value}`);
        }
        return lines;
    }
}
export class Gauge implements Metric {
    public readonly type = 'gauge';
    private readonly values = new Map<string, number>();
    public constructor(public readonly name: string, public readonly help: string) { }
    public set(value: number, labels: Labels = {}): void {
        this.values.set(serializeLabels(labels), value);
    }
    public collect(): string[] {
        if (this.values.size === 0) {
            return [`${this.name} 0`];
        }
        const lines: string[] = [];
        for (const [key, value] of this.values) {
            lines.push(`${this.name}${key} ${value}`);
        }
        return lines;
    }
}
const DEFAULT_BUCKETS = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000];
export class Histogram implements Metric {
    public readonly type = 'histogram';
    private readonly buckets: readonly number[];
    private readonly bucketCounts: number[];
    private sum = 0;
    private count = 0;
    public constructor(public readonly name: string, public readonly help: string, buckets: readonly number[] = DEFAULT_BUCKETS) {
        this.buckets = [...buckets].sort((a, b) => a - b);
        this.bucketCounts = new Array(this.buckets.length).fill(0);
    }
    public observe(value: number): void {
        for (let i = 0; i < this.buckets.length; i += 1) {
            const edge = this.buckets[i];
            if (edge !== undefined && value <= edge) {
                this.bucketCounts[i] = (this.bucketCounts[i] ?? 0) + 1;
            }
        }
        this.sum += value;
        this.count += 1;
    }
    public collect(): string[] {
        const lines: string[] = [];
        for (let i = 0; i < this.buckets.length; i += 1) {
            const edge = this.buckets[i] ?? 0;
            const bucketCount = this.bucketCounts[i] ?? 0;
            lines.push(`${this.name}_bucket{le="${edge}"} ${bucketCount}`);
        }
        lines.push(`${this.name}_bucket{le="+Inf"} ${this.count}`);
        lines.push(`${this.name}_sum ${this.sum}`);
        lines.push(`${this.name}_count ${this.count}`);
        return lines;
    }
}
export class MetricsRegistry {
    private readonly metrics: Metric[] = [];
    public counter(name: string, help: string): Counter {
        const metric = new Counter(name, help);
        this.metrics.push(metric);
        return metric;
    }
    public gauge(name: string, help: string): Gauge {
        const metric = new Gauge(name, help);
        this.metrics.push(metric);
        return metric;
    }
    public histogram(name: string, help: string, buckets?: readonly number[]): Histogram {
        const metric = new Histogram(name, help, buckets);
        this.metrics.push(metric);
        return metric;
    }
    public render(): string {
        const blocks: string[] = [];
        for (const metric of this.metrics) {
            const block = [
                `# HELP ${metric.name} ${metric.help}`,
                `# TYPE ${metric.name} ${metric.type}`,
                ...metric.collect(),
            ];
            blocks.push(block.join('\n'));
        }
        return `${blocks.join('\n\n')}\n`;
    }
}
export interface GatewayMetrics {
    readonly registry: MetricsRegistry;
    readonly requestsTotal: Counter;
    readonly piiRedactionsTotal: Counter;
    readonly injectionsBlockedTotal: Counter;
    readonly failOpenBypassTotal: Counter;
    readonly clientDisconnectsTotal: Counter;
    readonly rateLimitedTotal: Counter;
    readonly upstreamForwardLatencyMs: Histogram;
}
export function createGatewayMetrics(): GatewayMetrics {
    const registry = new MetricsRegistry();
    return {
        registry,
        requestsTotal: registry.counter('valence_requests_total', 'Total proxied requests by outcome.'),
        piiRedactionsTotal: registry.counter('valence_pii_redactions_total', 'Total PII/secret surrogates injected before upstream forwarding.'),
        injectionsBlockedTotal: registry.counter('valence_injections_blocked_total', 'Total prompts blocked by the injection shield.'),
        failOpenBypassTotal: registry.counter('valence_fail_open_bypass_total', 'Total subsystem failures bypassed while in FAIL_OPEN mode.'),
        clientDisconnectsTotal: registry.counter('valence_client_disconnects_total', 'Total client disconnects that aborted an upstream task.'),
        rateLimitedTotal: registry.counter('valence_rate_limited_total', 'Total requests rejected by the per-tenant rate limiter.'),
        upstreamForwardLatencyMs: registry.histogram('valence_upstream_forward_latency_ms', 'Latency in milliseconds from request receipt to upstream forward.'),
    };
}
