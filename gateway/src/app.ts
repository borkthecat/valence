/**
 * Valence Gateway - Application Bootstrap and Composition Root
 *
 * The only module allowed to touch validated environment configuration
 * and construct concrete subsystem instances. Everything below this file
 * receives its dependencies by injection, which is what keeps every other
 * module testable without a booted environment.
 *
 * Middleware order is a security property, not a style choice:
 *
 *   request-id -> helmet -> logger -> health (unauthenticated liveness)
 *   -> [auth -> json parser -> proxy] on /v1 only
 *   -> 404 catchall -> error boundary (terminal)
 */

import { createServer, Server } from 'node:http';
import type { Socket } from 'node:net';
import { randomUUID } from 'node:crypto';
import express, { Express, NextFunction, Request, Response } from 'express';
import helmet from 'helmet';
import pino, { Logger } from 'pino';
import pinoHttp from 'pino-http';
import { environment } from './config/environment';
import { TokenVault } from './core/crypto/tokenVault';
import {
  EmbeddingClassifierDetector,
  HeuristicPiiDetector,
  NullClassifierClient,
  PiiScanner,
} from './core/filters/piiScanner';
import {
  GuardModelDetector,
  HeuristicInjectionDetector,
  InjectionShield,
  NullGuardModelClient,
} from './core/filters/injectionShield';
import { createGatewayAuth } from './middleware/auth';
import {
  createErrorHandler,
  installProcessGuards,
  scrubSensitiveTraces,
} from './middleware/errorHandler';
import { createReverseProxy } from './proxy/reverseProxy';

const JSON_BODY_LIMIT = '2mb';
const SHUTDOWN_GRACE_MS = 10_000;

export function buildApp(logger: Logger): Express {
  const vault = TokenVault.getInstance();

  const scanner = new PiiScanner(vault, [
    new HeuristicPiiDetector(),
    // Swap the Null client for a real ClassifierClient implementation to
    // enable the cognitive tier; the scanner contract does not change.
    new EmbeddingClassifierDetector(new NullClassifierClient()),
  ]);

  const shield = new InjectionShield([
    new HeuristicInjectionDetector(),
    new GuardModelDetector(new NullGuardModelClient()),
  ]);

  const authenticate = createGatewayAuth(environment.GATEWAY_API_KEY, {
    onRejected: (context) => {
      logger.warn(
        {
          reason: context.reason,
          method: context.method,
          path: context.path,
        },
        'gateway auth rejected',
      );
    },
  });

  const proxy = createReverseProxy({
    upstreamBaseUrl: environment.UPSTREAM_PROVIDER_URL,
    upstreamApiKey: environment.UPSTREAM_API_KEY,
    securityMode: environment.SECURITY_MODE,
    vault,
    scanner,
    shield,
    sink: {
      onPromptBlocked: (event) => logger.warn(event, 'prompt rejected'),
      onFailOpenBypass: (event) =>
        logger.error(event, 'SECURITY BYPASS: subsystem failed in FAIL_OPEN'),
      onForwarded: (event) => logger.info(event, 'request forwarded'),
    },
  });

  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', false);

  // Request identity plus uniform trace cleanup on every outcome.
  // Both events are handled because they are not equivalent: 'finish'
  // fires on a completed response, 'close' fires on aborted ones too.
  // The registry is idempotent, so the overlap costs nothing.
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

  app.use(
    pinoHttp({
      logger,
      redact: {
        paths: [
          'req.headers.authorization',
          'req.headers["x-valence-key"]',
          'req.headers.cookie',
        ],
        censor: '[redacted]',
      },
    }),
  );

  // Liveness endpoint: unauthenticated by design so orchestrators can
  // probe it, and it discloses nothing about configuration.
  app.get('/healthz', (_req: Request, res: Response) => {
    res.status(200).json({ status: 'ok' });
  });

  app.use('/v1', authenticate);
  app.use('/v1', express.json({ limit: JSON_BODY_LIMIT }));
  app.post('/v1/*', proxy);

  app.use((_req: Request, res: Response) => {
    res.status(404).json({ error: 'NOT_FOUND' });
  });

  app.use(
    createErrorHandler({
      onGatewayError: (event) => logger.error(event, 'gateway error boundary'),
    }),
  );

  return app;
}

export function startGateway(): Server {
  const logger = pino({
    level: environment.NODE_ENV === 'production' ? 'info' : 'debug',
  });

  installProcessGuards();

  const app = buildApp(logger);
  const server = createServer(app);

  // Track live sockets so shutdown can sever stragglers after the grace
  // period instead of hanging on a slow or hostile client forever.
  const sockets = new Set<Socket>();
  server.on('connection', (socket) => {
    sockets.add(socket);
    socket.on('close', () => {
      sockets.delete(socket);
    });
  });

  server.listen(environment.PORT, () => {
    logger.info(
      {
        port: environment.PORT,
        securityMode: environment.SECURITY_MODE,
        upstream: environment.UPSTREAM_PROVIDER_URL,
      },
      'valence gateway listening',
    );
  });

  const shutdown = (signal: string): void => {
    logger.info({ signal }, 'graceful shutdown initiated');
    server.close(() => {
      // Vault teardown last: in-flight streams may still detokenize
      // until the final response completes.
      TokenVault.resetInstance();
      logger.info('shutdown complete');
      process.exit(0);
    });
    setTimeout(() => {
      logger.warn(
        { openSockets: sockets.size },
        'grace period expired, severing remaining sockets',
      );
      for (const socket of sockets) {
        socket.destroy();
      }
      TokenVault.resetInstance();
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
