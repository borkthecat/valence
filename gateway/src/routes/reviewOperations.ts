import { createHmac, createHash, randomUUID } from 'node:crypto';
import type { NextFunction, Request, Response, Router } from 'express';
import express from 'express';
import type { Logger } from 'pino';
import type { AuthenticatedRequest } from '../middleware/types';

const OPERATIONS_PATH = /^(?:\/reviews(?:\/[A-Za-z0-9-]+(?:\/(?:claim|release|decision|escalate|reopen|expire|cancel|audit))?)?|\/shadow-runs(?:\/(?:report|export|[A-Za-z0-9-]+(?:\/(?:outcome|compare|replay|expire|delete|audit))?))?)$/;
const OPERATIONS_SCOPES: Record<string, string> = {
    'POST /reviews': 'review:claim',
    'GET /reviews': 'review:read',
    'GET /reviews/:id': 'review:read',
    'GET /reviews/:id/audit': 'review:audit',
    'POST /reviews/:id/claim': 'review:claim',
    'POST /reviews/:id/release': 'review:claim',
    'POST /reviews/:id/decision': 'review:decide',
    'POST /reviews/:id/escalate': 'review:escalate',
    'POST /reviews/:id/reopen': 'review:override',
    'POST /reviews/:id/expire': 'review:retention',
    'POST /reviews/:id/cancel': 'review:retention',
    'POST /shadow-runs': 'shadow:submit',
    'GET /shadow-runs': 'shadow:read',
    'GET /shadow-runs/report': 'shadow:read',
    'GET /shadow-runs/export': 'shadow:audit',
    'GET /shadow-runs/:id': 'shadow:read',
    'GET /shadow-runs/:id/audit': 'shadow:audit',
    'POST /shadow-runs/:id/outcome': 'shadow:outcome',
    'POST /shadow-runs/:id/compare': 'shadow:compare',
    'POST /shadow-runs/:id/replay': 'shadow:replay',
    'POST /shadow-runs/:id/expire': 'shadow:retention',
    'POST /shadow-runs/:id/delete': 'shadow:retention',
};
function requiredScope(req: Request): string | undefined {
    let suffix = req.path;
    if (suffix.startsWith('/reviews/') && suffix !== '/reviews') {
        suffix = suffix.replace(/^\/reviews\/[^/]+/, '/reviews/:id');
    }
    if (suffix.startsWith('/shadow-runs/') && !['/shadow-runs/report', '/shadow-runs/export'].includes(suffix)) {
        suffix = suffix.replace(/^\/shadow-runs\/[^/]+/, '/shadow-runs/:id');
    }
    return OPERATIONS_SCOPES[`${req.method} ${suffix}`];
}
function bodyText(req: Request): string {
    if (['GET', 'HEAD'].includes(req.method)) return '';
    return req.body === undefined ? '' : JSON.stringify(req.body);
}
export function createReviewOperationsRouter(options: { baseUrl: string; internalKey: string; logger: Logger; audit?: { record(event: Record<string, unknown>): void }; }): Router {
    const router = express.Router();
    router.use(async (req: AuthenticatedRequest, res: Response, next: NextFunction): Promise<void> => {
        if (!OPERATIONS_PATH.test(req.path)) { next(); return; }
        const scope = requiredScope(req);
        const identity = req.valence;
        const adminScope = req.path.startsWith('/shadow-runs') ? 'shadow:admin' : 'review:admin';
        if (scope === undefined || identity === undefined || (!identity.scopes.includes(scope) && !identity.scopes.includes(adminScope))) {
            options.audit?.record({ type: 'review_authorization_rejected', method: req.method, path: req.path });
            res.status(403).json({ error: 'forbidden' }); return;
        }
        const actorId = identity.actorId;
        const timestamp = new Date().toISOString();
        const requestId = res.getHeader('x-request-id')?.toString() ?? randomUUID();
        const traceId = typeof req.headers['x-trace-id'] === 'string' ? req.headers['x-trace-id'].slice(0, 128) : requestId;
        const text = bodyText(req);
        const digest = createHash('sha256').update(text).digest('hex');
        const canonical = [timestamp, req.method, `/v1${req.path}`, identity.tenantId, actorId, identity.scopes.join(' '), requestId, traceId, digest].join('\n');
        const signature = createHmac('sha256', options.internalKey).update(canonical).digest('hex');
        try {
            const upstream = await fetch(new URL(`/v1${req.path}`, options.baseUrl), {
                method: req.method,
                headers: {
                    'content-type': 'application/json',
                    'x-valence-internal-timestamp': timestamp,
                    'x-valence-internal-signature': signature,
                    'x-valence-actor': actorId,
                    'x-valence-tenant': identity.tenantId,
                    'x-valence-scopes': identity.scopes.join(' '),
                    'x-request-id': requestId,
                    'x-trace-id': traceId,
                    ...(typeof req.headers['idempotency-key'] === 'string' ? { 'idempotency-key': req.headers['idempotency-key'] } : {}),
                },
                ...(['GET', 'HEAD'].includes(req.method) ? {} : { body: text }),
                signal: AbortSignal.timeout(5000),
            });
            const response = await upstream.text();
            res.status(upstream.status).type(upstream.headers.get('content-type') ?? 'application/json').send(response);
        } catch (error) {
            options.logger.error({ err: error, path: req.path }, 'review operations unavailable');
            options.audit?.record({ type: 'review_operations_failure', method: req.method, path: req.path });
            res.status(503).json({ error: 'service_unavailable' });
        }
    });
    return router;
}
