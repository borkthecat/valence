import { strict as assert } from 'node:assert';
import { createServer } from 'node:http';
import express, { type NextFunction, type Request, type Response } from 'express';
import pino from 'pino';
import type { AuthenticatedRequest } from '../src/middleware/types';
import { createReviewOperationsRouter } from '../src/routes/reviewOperations';

async function run(): Promise<void> {
    const app = express();
    let scopes = ['valence:proxy'];
    app.use((req: Request, _res: Response, next: NextFunction) => {
        (req as AuthenticatedRequest).valence = {
            tenantId: 'tenant-a',
            actorId: 'actor-a',
            scopes,
        };
        next();
    });
    app.use('/v1', createReviewOperationsRouter({
        baseUrl: 'http://127.0.0.1:1',
        internalKey: 'k'.repeat(32),
        logger: pino({ enabled: false }),
    }));
    app.post('/v1/messages', (_req: Request, res: Response) => res.status(204).end());
    const server = createServer(app);
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    try {
        const address = server.address();
        if (address === null || typeof address === 'string') throw new Error('server address unavailable');
        const base = `http://127.0.0.1:${address.port}`;
        assert.equal((await fetch(`${base}/v1/messages`, { method: 'POST' })).status, 204);
        assert.equal((await fetch(`${base}/v1/shadow-runs/report`)).status, 403);
        scopes = ['review:admin'];
        assert.equal((await fetch(`${base}/v1/shadow-runs/report`)).status, 403);
    }
    finally {
        await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    }
    process.stdout.write('operations-routing.smoke: OK\n');
}

run().catch((error) => {
    console.error('operations-routing.smoke: FAILED', error);
    process.exit(1);
});
