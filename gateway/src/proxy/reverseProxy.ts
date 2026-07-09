import { pipeline } from 'node:stream';
import axios, { AxiosInstance, AxiosResponse } from 'axios';
import type { RequestHandler, Response } from 'express';
import type { Readable } from 'node:stream';
import { z } from 'zod';
import type { SecurityMode } from '../config/environment';
import type { TokenVaultBackend } from '../core/crypto/tokenVault';
import { PiiScanner } from '../core/filters/piiScanner';
import type { GuardPolicy, InjectionDetectionContext, InjectionVerdict } from '../core/filters/injectionShield';
import { InjectionShield } from '../core/filters/injectionShield';
import { routeForProvenance } from '../core/filters/provenanceRouting';
import { SurrogateChunkReconstructor, createReconstitutionStream, } from '../core/streaming/chunkReconstructor';
import { registerSensitiveTrace, scrubSensitiveTraces, } from '../middleware/errorHandler';
import type { AuthenticatedRequest } from '../middleware/types';
const MESSAGE_CONTENT_MAX_CHARS = 200000;
const UPSTREAM_TIMEOUT_MS = 120000;
const FORWARDED_RESPONSE_HEADERS = ['content-type'] as const;
const FORWARDED_REQUEST_HEADERS = ['anthropic-version', 'accept'] as const;
const messageSchema = z
    .object({
    role: z.enum(['system', 'user', 'assistant', 'tool']),
    content: z.string().max(MESSAGE_CONTENT_MAX_CHARS),
})
    .passthrough();
const proxyBodySchema = z
    .object({
    model: z.string().min(1).max(256),
    messages: z.array(messageSchema).min(1).max(128),
    stream: z.boolean().optional(),
})
    .passthrough();
type ProxyBody = z.infer<typeof proxyBodySchema>;
type ProxyMessage = z.infer<typeof messageSchema>;
export class UpstreamConnectionError extends Error {
    public readonly status = 502;
    public constructor(cause?: unknown) {
        super('Upstream provider connection failed');
        this.name = 'UpstreamConnectionError';
        if (cause !== undefined) {
            (this as {
                cause?: unknown;
            }).cause = cause;
        }
    }
}
export interface ProxyEventSink {
    onPromptBlocked(event: {
        readonly requestId: string;
        readonly score: number;
        readonly ruleIds: readonly string[];
    }): void;
    onFailOpenBypass(event: {
        readonly requestId: string;
        readonly subsystem: 'injection-shield' | 'pii-scanner';
        readonly errorName: string;
    }): void;
    onForwarded(event: {
        readonly requestId: string;
        readonly tenantId: string;
        readonly upstreamStatus: number;
        readonly surrogatesInjected: number;
        readonly streamed: boolean;
        readonly forwardLatencyMs: number;
    }): void;
    onClientDisconnect?(event: {
        readonly requestId: string;
        readonly phase: 'pre-upstream' | 'streaming';
    }): void;
}
export interface ReverseProxyDeps {
    readonly upstreamBaseUrl: string;
    readonly upstreamApiKey: string;
    readonly securityMode: SecurityMode;
    readonly vault: TokenVaultBackend;
    readonly scanner: PiiScanner;
    readonly shield: InjectionShield;
    readonly guardUserPolicy: GuardPolicy;
    readonly http?: AxiosInstance;
    readonly sink?: ProxyEventSink;
}
function requestIdOf(res: Response): string {
    const header = res.getHeader('x-request-id');
    return typeof header === 'string' ? header : 'unassigned';
}
function isShieldTarget(message: ProxyMessage): boolean {
    return message.role === 'user' || message.role === 'tool';
}
function guardContextForMessage(message: ProxyMessage, userPolicy: GuardPolicy): InjectionDetectionContext {
    if (message.role === 'tool') {
        return routeForProvenance({ boundary: 'retrieved_document' });
    }
    if (userPolicy === 'direct') {
        return routeForProvenance({ boundary: 'user_session' });
    }
    return { policy: userPolicy };
}
export function createReverseProxy(deps: ReverseProxyDeps): RequestHandler {
    const http = deps.http ??
        axios.create({
            timeout: UPSTREAM_TIMEOUT_MS,
            maxRedirects: 0,
        });
    const failClosed = deps.securityMode === 'FAIL_CLOSED';
    async function guarded<T>(operation: () => Promise<T>, fallback: T, subsystem: 'injection-shield' | 'pii-scanner', requestId: string): Promise<T> {
        try {
            return await operation();
        }
        catch (error) {
            if (failClosed) {
                throw error;
            }
            deps.sink?.onFailOpenBypass({
                requestId,
                subsystem,
                errorName: error instanceof Error ? error.name : 'NonErrorThrown',
            });
            return fallback;
        }
    }
    const benignVerdict: InjectionVerdict = {
        blocked: false,
        score: 0,
        threshold: Number.POSITIVE_INFINITY,
        matches: [],
    };
    return function reverseProxyHandler(req: AuthenticatedRequest, res, next): void {
        void (async (): Promise<void> => {
            const requestId = requestIdOf(res);
            const tenantId = req.valence?.tenantId ?? 'unidentified';
            const startedAt = process.hrtime.bigint();
            let streaming = false;
            const parsed = proxyBodySchema.safeParse(req.body);
            if (!parsed.success) {
                res.status(400).json({
                    error: 'INVALID_REQUEST_SHAPE',
                    requestId,
                    issues: parsed.error.issues.map((issue) => ({
                        path: issue.path.join('.'),
                        message: issue.message,
                    })),
                });
                return;
            }
            const body: ProxyBody = parsed.data;
            for (const message of body.messages) {
                if (!isShieldTarget(message)) {
                    continue;
                }
                const verdict = await guarded(
                    () => deps.shield.evaluate(message.content, guardContextForMessage(message, deps.guardUserPolicy)),
                    benignVerdict,
                    'injection-shield',
                    requestId,
                );
                if (verdict.blocked) {
                    const ruleIds = verdict.matches.map((match) => match.ruleId);
                    deps.sink?.onPromptBlocked({
                        requestId,
                        score: verdict.score,
                        ruleIds,
                    });
                    res.status(403).json({
                        error: 'PROMPT_REJECTED',
                        requestId,
                        score: verdict.score,
                        threshold: verdict.threshold,
                        ruleIds,
                    });
                    return;
                }
            }
            let surrogatesInjected = 0;
            const allowedSurrogates = new Set<string>();
            const maskedMessages: ProxyMessage[] = [];
            for (const message of body.messages) {
                const scanResult = await guarded(() => deps.scanner.scan(message.content), { sanitizedText: message.content, findings: [], surrogates: [] }, 'pii-scanner', requestId);
                surrogatesInjected += scanResult.findings.length;
                for (const surrogate of scanResult.surrogates) {
                    allowedSurrogates.add(surrogate);
                }
                maskedMessages.push({ ...message, content: scanResult.sanitizedText });
            }
            const maskedBody: ProxyBody = { ...body, messages: maskedMessages };
            const requestHeaders: Record<string, string> = {
                'content-type': 'application/json',
                'accept-encoding': 'identity',
                authorization: `Bearer ${deps.upstreamApiKey}`,
                'x-api-key': deps.upstreamApiKey,
            };
            for (const name of FORWARDED_REQUEST_HEADERS) {
                const value = req.headers[name];
                if (typeof value === 'string') {
                    requestHeaders[name] = value;
                }
            }
            const targetUrl = new URL(req.originalUrl, deps.upstreamBaseUrl).toString();
            const upstreamAbort = new AbortController();
            res.on('close', () => {
                upstreamAbort.abort();
                if (!res.writableFinished) {
                    deps.sink?.onClientDisconnect?.({
                        requestId,
                        phase: streaming ? 'streaming' : 'pre-upstream',
                    });
                }
            });
            let upstream: AxiosResponse<Readable>;
            try {
                upstream = await http.post<Readable>(targetUrl, maskedBody, {
                    headers: requestHeaders,
                    responseType: 'stream',
                    signal: upstreamAbort.signal,
                    validateStatus: () => true,
                });
            }
            catch (error) {
                throw new UpstreamConnectionError(error);
            }
            const reconstructor = new SurrogateChunkReconstructor(deps.vault, {
                unresolvedPolicy: failClosed ? 'throw' : 'passthrough',
                allowedSurrogates,
            });
            registerSensitiveTrace(res, reconstructor);
            streaming = true;
            res.status(upstream.status);
            for (const name of FORWARDED_RESPONSE_HEADERS) {
                const value = upstream.headers[name];
                if (typeof value === 'string') {
                    res.set(name, value);
                }
            }
            deps.sink?.onForwarded({
                requestId,
                tenantId,
                upstreamStatus: upstream.status,
                surrogatesInjected,
                streamed: body.stream === true,
                forwardLatencyMs: Number(process.hrtime.bigint() - startedAt) / 1e6,
            });
            pipeline(upstream.data, createReconstitutionStream(reconstructor), res, (error) => {
                if (error !== null && error !== undefined) {
                    next(error);
                    return;
                }
                scrubSensitiveTraces(res);
            });
        })().catch(next);
    };
}
