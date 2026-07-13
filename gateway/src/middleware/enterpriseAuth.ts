import { expressjwt } from 'express-jwt';
import type { GetVerificationKey } from 'express-jwt';
import jwksRsa from 'jwks-rsa';
import { environment } from '../config/environment';
import { createGatewayAuth } from './auth';
import type { RequestHandler } from 'express';

export function createEnterpriseIngestAuth(): RequestHandler {
    if (environment.ENTERPRISE_INGEST_AUTH_MODE === 'api_key') {
        return createGatewayAuth(environment.GATEWAY_API_KEY, {
            tenantContext: {
                tenantId: 'enterprise-local',
                actorId: 'enterprise-ingest-service',
                scopes: ['valence:ingest'],
            },
        });
    }
    const jwksUri = environment.JWKS_URI;
    if (jwksUri === undefined) {
        return (_req, res): void => {
            res.status(503).json({ error: 'JWKS_NOT_CONFIGURED' });
        };
    }
    return expressjwt({
        secret: jwksRsa.expressJwtSecret({
            cache: true,
            rateLimit: true,
            jwksRequestsPerMinute: 5,
            jwksUri,
        }) as GetVerificationKey,
        audience: environment.JWT_AUDIENCE,
        issuer: environment.JWT_ISSUER,
        algorithms: ['RS256'],
    });
}
