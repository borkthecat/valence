/**
 * Valence Gateway - Reverse Proxy Orchestrator
 *
 * The primary data path. For every inbound completion request:
 *
 *   1. VALIDATE     Zod-checks the JSON body shape before any content is
 *                   inspected; malformed requests never reach a scanner.
 *   2. SHIELD       Runs the injection shield over user-authored turns.
 *                   A blocked verdict returns 403 with rule ids only.
 *   3. MASK         Runs the PII scanner over every message; raw values
 *                   are swapped for TokenVault surrogates.
 *   4. FORWARD      Streams the masked body upstream via Axios with the
 *                   provider credential attached server-side. The client
 *                   credential never leaves the gateway, and the provider
 *                   credential never reaches the client.
 *   5. RECONSTITUTE Pipes the upstream byte stream through the
 *                   SurrogateChunkReconstructor so surrogates the model
 *                   echoes back are restored before reaching the client,
 *                   even when a marker straddles transport chunks.
 *
 * SECURITY_MODE governs subsystem failure only, never verdicts:
 * FAIL_CLOSED rethrows scanner/shield faults to the error boundary;
 * FAIL_OPEN logs the bypass and forwards the original text. A blocked
 * verdict blocks in both modes.
 *
 * Known scope boundary, stated rather than hidden: reconstitution runs at
 * the raw byte level. A surrogate split across two SEPARATE SSE events
 * (interleaved with framing bytes) requires provider-specific delta
 * parsing to reassemble; that codec belongs in a per-provider adapter,
 * not in this transport-neutral path. Same-event and same-stream splits,
 * the overwhelmingly common case, are fully handled.
 */

import { pipeline } from 'node:stream';
import axios, { AxiosInstance, AxiosResponse } from 'axios';
import type { RequestHandler, Response } from 'express';
import type { Readable } from 'node:stream';
import { z } from 'zod';
import type { SecurityMode } from '../config/environment';
import { TokenVault } from '../core/crypto/tokenVault';
import { PiiScanner } from '../core/filters/piiScanner';
import type { InjectionVerdict } from '../core/filters/injectionShield';
import { InjectionShield } from '../core/filters/injectionShield';
import {
  SurrogateChunkReconstructor,
  createReconstitutionStream,
} from '../core/streaming/chunkReconstructor';
import {
  registerSensitiveTrace,
  scrubSensitiveTraces,
} from '../middleware/errorHandler';

const MESSAGE_CONTENT_MAX_CHARS = 200_000;
const UPSTREAM_TIMEOUT_MS = 120_000;

/** Response headers copied from upstream verbatim. Everything else is
 *  either hop-by-hop, invalidated by reconstitution (content-length
 *  changes when surrogates expand to raw values), or gateway-owned. */
const FORWARDED_RESPONSE_HEADERS = ['content-type'] as const;

/** Request headers forwarded to the provider. Client Authorization and
 *  x-valence-key are deliberately absent. */
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

/** Raised when the provider cannot be reached or times out. The error
 *  boundary maps this NAME to 502 UPSTREAM_UNREACHABLE; keep it stable. */
export class UpstreamConnectionError extends Error {
  public readonly status = 502;

  public constructor(cause?: unknown) {
    super('Upstream provider connection failed');
    this.name = 'UpstreamConnectionError';
    if (cause !== undefined) {
      (this as { cause?: unknown }).cause = cause;
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
    readonly upstreamStatus: number;
    readonly surrogatesInjected: number;
    readonly streamed: boolean;
  }): void;
}

export interface ReverseProxyDeps {
  readonly upstreamBaseUrl: string;
  readonly upstreamApiKey: string;
  readonly securityMode: SecurityMode;
  readonly vault: TokenVault;
  readonly scanner: PiiScanner;
  readonly shield: InjectionShield;
  /** Injectable for tests; defaults to a dedicated Axios instance. */
  readonly http?: AxiosInstance;
  readonly sink?: ProxyEventSink;
}

function requestIdOf(res: Response): string {
  const header = res.getHeader('x-request-id');
  return typeof header === 'string' ? header : 'unassigned';
}

/** Only user-authored turns are adversarial input to the shield; system
 *  and assistant turns are the client application's own trusted context. */
function isShieldTarget(message: ProxyMessage): boolean {
  return message.role === 'user' || message.role === 'tool';
}

export function createReverseProxy(deps: ReverseProxyDeps): RequestHandler {
  const http =
    deps.http ??
    axios.create({
      timeout: UPSTREAM_TIMEOUT_MS,
      maxRedirects: 0,
    });

  const failClosed = deps.securityMode === 'FAIL_CLOSED';

  /** Applies the SECURITY_MODE contract to a subsystem call: FAIL_CLOSED
   *  rethrows into the error boundary, FAIL_OPEN records the bypass and
   *  substitutes the fallback so traffic continues unscanned. */
  async function guarded<T>(
    operation: () => Promise<T>,
    fallback: T,
    subsystem: 'injection-shield' | 'pii-scanner',
    requestId: string,
  ): Promise<T> {
    try {
      return await operation();
    } catch (error) {
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

  return function reverseProxyHandler(req, res, next): void {
    void (async (): Promise<void> => {
      const requestId = requestIdOf(res);

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

      // Stage 2: SHIELD. Sequential on purpose: the first blocked turn
      // ends the request without spending scanner work on the rest.
      for (const message of body.messages) {
        if (!isShieldTarget(message)) {
          continue;
        }
        const verdict = await guarded(
          () => deps.shield.evaluate(message.content),
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

      // Stage 3: MASK every message, regardless of role: PII in a system
      // prompt leaks exactly as badly as PII in a user turn. The exact
      // surrogates minted here form this request's restoration allowlist;
      // the response stream may resolve these and nothing else.
      let surrogatesInjected = 0;
      const allowedSurrogates = new Set<string>();
      const maskedMessages: ProxyMessage[] = [];
      for (const message of body.messages) {
        const scanResult = await guarded(
          () => deps.scanner.scan(message.content),
          { sanitizedText: message.content, findings: [], surrogates: [] },
          'pii-scanner',
          requestId,
        );
        surrogatesInjected += scanResult.findings.length;
        for (const surrogate of scanResult.surrogates) {
          allowedSurrogates.add(surrogate);
        }
        maskedMessages.push({ ...message, content: scanResult.sanitizedText });
      }
      const maskedBody: ProxyBody = { ...body, messages: maskedMessages };

      // Stage 4: FORWARD. accept-encoding is pinned to identity so the
      // reconstitution stream always sees plaintext bytes, never gzip.
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

      // A client that disconnects must not leave the provider streaming
      // into a dead pipe: tie the upstream request lifetime to the
      // client response socket. res 'close' also fires after a normal
      // finish, at which point aborting a completed exchange is a no-op.
      const upstreamAbort = new AbortController();
      res.on('close', () => {
        upstreamAbort.abort();
      });

      let upstream: AxiosResponse<Readable>;
      try {
        upstream = await http.post<Readable>(targetUrl, maskedBody, {
          headers: requestHeaders,
          responseType: 'stream',
          signal: upstreamAbort.signal,
          // Provider 4xx/5xx bodies flow back through reconstitution
          // like any other payload; only transport failure throws.
          validateStatus: () => true,
        });
      } catch (error) {
        throw new UpstreamConnectionError(error);
      }

      // Stage 5: RECONSTITUTE. Under FAIL_CLOSED an unresolvable marker
      // kills the stream via the error boundary (socket severed if
      // mid-flight); under FAIL_OPEN it passes through verbatim.
      const reconstructor = new SurrogateChunkReconstructor(deps.vault, {
        unresolvedPolicy: failClosed ? 'throw' : 'passthrough',
        allowedSurrogates,
      });
      registerSensitiveTrace(res, reconstructor);

      res.status(upstream.status);
      for (const name of FORWARDED_RESPONSE_HEADERS) {
        const value = upstream.headers[name];
        if (typeof value === 'string') {
          res.set(name, value);
        }
      }

      deps.sink?.onForwarded({
        requestId,
        upstreamStatus: upstream.status,
        surrogatesInjected,
        streamed: body.stream === true,
      });

      pipeline(
        upstream.data,
        createReconstitutionStream(reconstructor),
        res,
        (error) => {
          if (error !== null && error !== undefined) {
            next(error);
            return;
          }
          // Success path performs the same cleanup as the failure path:
          // no branch may leave reconstituted plaintext staged.
          scrubSensitiveTraces(res);
        },
      );
    })().catch(next);
  };
}
