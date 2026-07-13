import { createServer, Server } from 'node:http';
import type { Socket } from 'node:net';
import { randomUUID } from 'node:crypto';
import express, { Express, NextFunction, Request, Response } from 'express';
import helmet from 'helmet';
import pino, { Logger } from 'pino';
import pinoHttp from 'pino-http';
import { environment } from './config/environment';
import { RedisTokenVault, TokenVault, type TokenVaultBackend } from './core/crypto/tokenVault';
import { EmbeddingClassifierDetector, HeuristicPiiDetector, NullClassifierClient, PiiScanner, parsePiiCategoryThresholds, } from './core/filters/piiScanner';
import { GuardModelDetector, HeuristicInjectionDetector, InjectionShield, NullGuardModelClient, } from './core/filters/injectionShield';
import { createGatewayAuth } from './middleware/auth';
import { createJwtAuth } from './middleware/jwtAuth';
import { createTenantRateLimiter } from './middleware/rateLimiter';
import { createErrorHandler, installProcessGuards, scrubSensitiveTraces, } from './middleware/errorHandler';
import { createReverseProxy } from './proxy/reverseProxy';
import { createGatewayMetrics } from './observability/metrics';
import { createAuditLog } from './observability/auditLog';
import { createShadowReviewLog, parseShadowReviewSources } from './observability/shadowReviewLog';
import { ingestRouter } from './routes/ingest';
import { createReviewOperationsRouter } from './routes/reviewOperations';
import { disconnectProducer } from './services/kafkaProducer';
import { HttpClassifierClient, HttpGuardModelClient, LocalGuardModelClient } from './services/modelClients';
const JSON_BODY_LIMIT = `${environment.MAX_PAYLOAD_KB}kb`;
const SHUTDOWN_GRACE_MS = 10000;
let activeVault: TokenVaultBackend | null = null;

function createConfiguredVault(): TokenVaultBackend {
    if (environment.REDIS_URL !== undefined) {
        return new RedisTokenVault(environment.REDIS_URL, environment.GATEWAY_API_KEY);
    }
    return TokenVault.getInstance();
}

async function shutdownVault(): Promise<void> {
    if (activeVault instanceof RedisTokenVault) {
        await activeVault.disconnect();
        activeVault = null;
        return;
    }
    TokenVault.resetInstance();
    activeVault = null;
}

export async function shutdownGatewayResources(): Promise<void> {
    await shutdownVault();
    await disconnectProducer();
}

export function buildApp(logger: Logger): Express {
    const vault = createConfiguredVault();
    activeVault = vault;
    const classifierClient = environment.PII_CLASSIFIER_URL === undefined
        ? new NullClassifierClient()
        : new HttpClassifierClient({
            url: environment.PII_CLASSIFIER_URL,
            timeoutMs: environment.MODEL_SERVICE_TIMEOUT_MS,
            ...(environment.PII_CLASSIFIER_API_KEY === undefined ? {} : { apiKey: environment.PII_CLASSIFIER_API_KEY }),
        });
    const guardClient = environment.GUARD_MODEL_PATH !== undefined
        ? new LocalGuardModelClient(environment.GUARD_MODEL_PATH, environment.GUARD_MODEL_SHA256)
        : environment.GUARD_MODEL_URL !== undefined
        ? new HttpGuardModelClient({
            url: environment.GUARD_MODEL_URL,
            timeoutMs: environment.MODEL_SERVICE_TIMEOUT_MS,
            ...(environment.GUARD_MODEL_API_KEY === undefined ? {} : { apiKey: environment.GUARD_MODEL_API_KEY }),
        })
        : new NullGuardModelClient();
    const scanner = new PiiScanner(vault, [
        new HeuristicPiiDetector(),
        new EmbeddingClassifierDetector(classifierClient, {
            minimumScore: environment.PII_CLASSIFIER_MINIMUM_SCORE,
            categoryMinimumScores: parsePiiCategoryThresholds(environment.PII_CLASSIFIER_LABEL_THRESHOLDS),
        }),
    ]);
    const shield = new InjectionShield([
        new HeuristicInjectionDetector(),
        new GuardModelDetector(guardClient, { enforcement: environment.GUARD_MODEL_ENFORCEMENT }),
    ]);
    const metrics = createGatewayMetrics();
    const audit = createAuditLog(environment.AUDIT_LOG_PATH);
    const shadowReview = createShadowReviewLog(environment.SHADOW_REVIEW_LOG_PATH);
    const shadowReviewSources = parseShadowReviewSources(environment.SHADOW_REVIEW_SOURCES);
    const apiKeyAuth = createGatewayAuth(environment.GATEWAY_API_KEY, {
        tenantContext: {
            tenantId: 'api-key',
            actorId: 'api-key-service',
            scopes: environment.GATEWAY_API_KEY_SCOPES.split(/[\s,]+/).filter(Boolean),
        },
        onRejected: (context) => {
            logger.warn({
                reason: context.reason,
                method: context.method,
                path: context.path,
            }, 'gateway auth rejected');
            audit?.record({
                type: 'auth_rejected',
                reason: context.reason,
                method: context.method,
                path: context.path,
            });
        },
    });
    const authenticate = environment.AUTH_MODE === 'jwt'
        ? createJwtAuth({
            algorithm: environment.JWT_ALGORITHM,
            ...(environment.JWT_SECRET === undefined ? {} : { secret: environment.JWT_SECRET }),
            ...(environment.JWT_PUBLIC_KEY_PEM === undefined
                ? {}
                : { publicKeyPem: environment.JWT_PUBLIC_KEY_PEM }),
            requiredScope: environment.JWT_REQUIRED_SCOPE,
            ...(environment.JWT_ISSUER === undefined
                ? {}
                : { issuer: environment.JWT_ISSUER }),
            ...(environment.JWT_AUDIENCE === undefined
                ? {}
                : { audience: environment.JWT_AUDIENCE }),
        }, {
            onRejected: (context) => {
                logger.warn(context, 'jwt auth rejected');
                audit?.record({
                    type: 'jwt_rejected',
                    reason: context.reason,
                    method: context.method,
                    path: context.path,
                });
            },
        })
        : apiKeyAuth;
    const rateLimiter = createTenantRateLimiter({
        maxRequests: environment.RATE_LIMIT_MAX_REQUESTS,
        windowMs: environment.RATE_LIMIT_WINDOW_MS,
    }, {
        onRateLimited: (context) => {
            metrics.rateLimitedTotal.inc({ tenant: context.tenantId });
            audit?.record({
                type: 'rate_limited',
                tenant_id: context.tenantId,
                method: context.method,
                path: context.path,
                retry_after_seconds: context.retryAfterSeconds,
            });
        },
    });
    const proxy = createReverseProxy({
        upstreamBaseUrl: environment.UPSTREAM_PROVIDER_URL,
        upstreamApiKey: environment.UPSTREAM_API_KEY,
        securityMode: environment.SECURITY_MODE,
        vault,
        scanner,
        shield,
        guardUserPolicy: environment.GUARD_USER_POLICY,
        shadowReviewSources,
        sink: {
            onPromptBlocked: (event) => {
                metrics.injectionsBlockedTotal.inc();
                logger.warn(event, 'prompt rejected');
                audit?.record({
                    type: 'prompt_blocked',
                    request_id: event.requestId,
                    score: event.score,
                    rule_count: event.ruleIds.length,
                });
            },
            onFailOpenBypass: (event) => {
                metrics.failOpenBypassTotal.inc({ subsystem: event.subsystem });
                logger.error(event, 'SECURITY BYPASS: subsystem failed in FAIL_OPEN');
                audit?.record({
                    type: 'fail_open_bypass',
                    request_id: event.requestId,
                    subsystem: event.subsystem,
                    error_name: event.errorName,
                });
            },
            onForwarded: (event) => {
                metrics.piiRedactionsTotal.inc({ tenant: event.tenantId }, event.surrogatesInjected);
                metrics.upstreamForwardLatencyMs.observe(event.forwardLatencyMs);
                logger.info(event, 'request forwarded');
                audit?.record({
                    type: 'request_forwarded',
                    request_id: event.requestId,
                    tenant_id: event.tenantId,
                    upstream_status: event.upstreamStatus,
                    surrogates_injected: event.surrogatesInjected,
                    streamed: event.streamed,
                });
            },
            onClientDisconnect: (event) => {
                metrics.clientDisconnectsTotal.inc({ phase: event.phase });
                logger.warn(event, 'client disconnected; upstream task aborted');
                audit?.record({
                    type: 'client_disconnect',
                    request_id: event.requestId,
                    phase: event.phase,
                });
            },
            onShadowReviewEvent: (event) => {
                shadowReview?.record(event);
                logger.info({
                    requestId: event.requestId,
                    sourceId: event.sourceId,
                    policy: event.policy,
                    score: event.score,
                }, 'shadow review event captured');
            },
        },
    });
    const app = express();
    app.disable('x-powered-by');
    app.set('trust proxy', false);
    app.use((_req: Request, res: Response, next: NextFunction) => {
        res.set('x-request-id', randomUUID());
        res.on('finish', () => {
            scrubSensitiveTraces(res);
        });
        res.on('close', () => {
            scrubSensitiveTraces(res);
        });
        next();
    });
    app.use(helmet());
    app.use(pinoHttp({
        logger,
        redact: {
            paths: [
                'req.headers.authorization',
                'req.headers["x-valence-key"]',
                'req.headers.cookie',
            ],
            censor: '[redacted]',
        },
    }));
    app.use('/api/v1/ingest', express.json({ limit: JSON_BODY_LIMIT }));
    app.use(ingestRouter);
    app.get('/healthz', (_req: Request, res: Response) => {
        res.status(200).json({ status: 'ok' });
    });
    app.get('/health', (_req: Request, res: Response) => {
        res.status(200).json({ status: 'HEALTHY' });
    });
    app.get('/metrics', apiKeyAuth, (_req: Request, res: Response) => {
        res.type('text/plain; version=0.0.4; charset=utf-8').send(metrics.registry.render());
    });
    app.use('/v1', authenticate);
    app.use('/v1', rateLimiter);
    app.use('/v1', (req: Request, res: Response, next: NextFunction) => {
        res.on('finish', () => {
            const tenantId = (req as Request & {
                valence?: {
                    tenantId: string;
                };
                }).valence?.tenantId ??
                'unidentified';
            metrics.requestsTotal.inc({
                tenant: tenantId,
                method: req.method,
                status_class: `${Math.floor(res.statusCode / 100)}xx`,
            });
        });
        next();
    });
    app.use('/v1', express.json({ limit: JSON_BODY_LIMIT }));
    if (environment.REVIEW_OPERATIONS_URL !== undefined && environment.REVIEW_OPERATIONS_INTERNAL_KEY !== undefined) {
        app.use('/v1', createReviewOperationsRouter({
            baseUrl: environment.REVIEW_OPERATIONS_URL,
            internalKey: environment.REVIEW_OPERATIONS_INTERNAL_KEY,
            logger,
            ...(audit === null ? {} : { audit }),
        }));
    }
    app.post('/v1/*', proxy);
    app.use((_req: Request, res: Response) => {
        res.status(404).json({ error: 'NOT_FOUND' });
    });
    app.use(createErrorHandler({
        onGatewayError: (event) => logger.error(event, 'gateway error boundary'),
    }));
    return app;
}
export function startGateway(): Server {
    const logger = pino({
        level: environment.NODE_ENV === 'production' ? 'info' : 'debug',
        base: { component: 'gateway-proxy' },
        timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
        formatters: {
            level: (label) => ({ level: label.toUpperCase() }),
        },
    });
    installProcessGuards();
    const app = buildApp(logger);
    const server = createServer(app);
    const sockets = new Set<Socket>();
    server.on('connection', (socket) => {
        sockets.add(socket);
        socket.on('close', () => {
            sockets.delete(socket);
        });
    });
    server.listen(environment.PORT, () => {
        logger.info({
            port: environment.PORT,
            securityMode: environment.SECURITY_MODE,
            upstream: environment.UPSTREAM_PROVIDER_URL,
        }, 'valence gateway listening');
    });
    const shutdown = (signal: string): void => {
        logger.info({ signal }, 'graceful shutdown initiated');
        server.close(() => {
            shutdownGatewayResources()
                .catch((error: unknown) => logger.warn({ error }, 'gateway resource shutdown failed'))
                .finally(() => {
                logger.info('shutdown complete');
                process.exit(0);
            });
        });
        setTimeout(() => {
            logger.warn({ openSockets: sockets.size }, 'grace period expired, severing remaining sockets');
            for (const socket of sockets) {
                socket.destroy();
            }
            void shutdownVault();
            process.exit(1);
        }, SHUTDOWN_GRACE_MS).unref();
    };
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));
    return server;
}
if (require.main === module) {
    startGateway();
}
