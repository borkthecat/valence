import { randomUUID } from 'node:crypto';
import type { ErrorRequestHandler, Response } from 'express';
import { PiiScanError } from '../core/filters/piiScanner';
import { InjectionShieldError } from '../core/filters/injectionShield';
import { UnresolvedSurrogateError } from '../core/streaming/chunkReconstructor';
export interface SensitiveTrace {
    scrub(): void;
}
const traceRegistry = new WeakMap<Response, Set<SensitiveTrace>>();
export function registerSensitiveTrace(res: Response, trace: SensitiveTrace): void {
    const existing = traceRegistry.get(res);
    if (existing !== undefined) {
        existing.add(trace);
        return;
    }
    traceRegistry.set(res, new Set([trace]));
}
export function scrubSensitiveTraces(res: Response): number {
    const traces = traceRegistry.get(res);
    if (traces === undefined) {
        return 0;
    }
    let scrubbed = 0;
    for (const trace of traces) {
        try {
            trace.scrub();
            scrubbed += 1;
        }
        catch {
        }
    }
    traceRegistry.delete(res);
    return scrubbed;
}
interface Classification {
    readonly status: number;
    readonly code: string;
}
function hasHttpStatus(error: unknown): error is {
    status: number;
} {
    if (typeof error !== 'object' || error === null) {
        return false;
    }
    const status = (error as {
        status?: unknown;
    }).status;
    return typeof status === 'number' && status >= 400 && status <= 599;
}
function classify(error: unknown): Classification {
    if (error instanceof PiiScanError || error instanceof InjectionShieldError) {
        return { status: 502, code: 'SECURITY_SUBSYSTEM_FAILURE' };
    }
    if (error instanceof UnresolvedSurrogateError) {
        return { status: 502, code: 'STREAM_RECONSTITUTION_FAILURE' };
    }
    if (error instanceof Error && error.name === 'UpstreamConnectionError') {
        return { status: 502, code: 'UPSTREAM_UNREACHABLE' };
    }
    if (hasHttpStatus(error)) {
        return { status: error.status, code: 'REQUEST_REJECTED' };
    }
    return { status: 500, code: 'GATEWAY_INTERNAL_FAILURE' };
}
export interface GatewayErrorEvent {
    readonly requestId: string;
    readonly method: string;
    readonly path: string;
    readonly errorName: string;
    readonly code: string;
    readonly status: number;
    readonly phase: 'pre-response' | 'mid-stream';
    readonly tracesScrubbed: number;
}
export interface ErrorEventSink {
    onGatewayError(event: GatewayErrorEvent): void;
}
export function createErrorHandler(sink?: ErrorEventSink): ErrorRequestHandler {
    return function gatewayErrorBoundary(error, req, res, _next): void {
        const tracesScrubbed = scrubSensitiveTraces(res);
        const { status, code } = classify(error);
        const requestIdHeader = res.getHeader('x-request-id');
        const requestId = typeof requestIdHeader === 'string' && requestIdHeader.length > 0
            ? requestIdHeader
            : randomUUID();
        const errorName = error instanceof Error ? error.name : 'NonErrorThrown';
        if (res.headersSent) {
            sink?.onGatewayError({
                requestId,
                method: req.method,
                path: req.path,
                errorName,
                code,
                status,
                phase: 'mid-stream',
                tracesScrubbed,
            });
            res.destroy();
            if (res.socket !== null && !res.socket.destroyed) {
                res.socket.destroy();
            }
            return;
        }
        sink?.onGatewayError({
            requestId,
            method: req.method,
            path: req.path,
            errorName,
            code,
            status,
            phase: 'pre-response',
            tracesScrubbed,
        });
        res
            .status(status)
            .set('x-request-id', requestId)
            .json({ error: code, requestId });
    };
}
let processGuardsInstalled = false;
export function installProcessGuards(beforeExit?: () => void): (() => void) | null {
    if (processGuardsInstalled) {
        return null;
    }
    processGuardsInstalled = true;
    const onFatal = (kind: string) => (cause: unknown): void => {
        const name = cause instanceof Error ? cause.name : 'NonErrorThrown';
        process.stderr.write(`[valence] FATAL ${kind}: ${name} - fail-closed shutdown.\n`);
        try {
            beforeExit?.();
        }
        catch {
        }
        process.exit(1);
    };
    const onUncaught = onFatal('uncaughtException');
    const onUnhandled = onFatal('unhandledRejection');
    process.on('uncaughtException', onUncaught);
    process.on('unhandledRejection', onUnhandled);
    return function uninstallProcessGuards(): void {
        process.removeListener('uncaughtException', onUncaught);
        process.removeListener('unhandledRejection', onUnhandled);
        processGuardsInstalled = false;
    };
}
