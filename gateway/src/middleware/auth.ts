import { createHash, timingSafeEqual } from 'node:crypto';
import type { NextFunction, Request, RequestHandler, Response } from 'express';
import type { AuthenticatedRequest, TenantContext } from './types';
export const GATEWAY_KEY_HEADER = 'x-valence-key';
const MAX_CREDENTIAL_LENGTH = 512;
export interface GatewayAuthOptions {
    readonly tenantContext?: TenantContext;
    readonly onRejected?: (context: {
        readonly reason: 'missing' | 'invalid' | 'oversized';
        readonly method: string;
        readonly path: string;
        readonly remoteAddress: string | undefined;
    }) => void;
}
function sha256(value: string): Buffer {
    return createHash('sha256').update(value, 'utf8').digest();
}
function extractCredential(req: Request): string | null {
    const headerValue = req.headers[GATEWAY_KEY_HEADER];
    if (typeof headerValue === 'string' && headerValue.length > 0) {
        return headerValue;
    }
    if (Array.isArray(headerValue)) {
        return null;
    }
    const authorization = req.headers.authorization;
    if (typeof authorization !== 'string') {
        return null;
    }
    const [scheme, ...rest] = authorization.split(' ');
    if (scheme === undefined ||
        scheme.toLowerCase() !== 'bearer' ||
        rest.length !== 1) {
        return null;
    }
    const token = rest[0];
    return token !== undefined && token.length > 0 ? token : null;
}
function rejectUnauthorized(res: Response): void {
    res
        .status(401)
        .set('WWW-Authenticate', 'Bearer realm="valence"')
        .json({ error: 'unauthorized' });
}
export function createGatewayAuth(expectedKey: string, options: GatewayAuthOptions = {}): RequestHandler {
    if (expectedKey.length < 32) {
        throw new RangeError('createGatewayAuth: expectedKey must be at least 32 characters');
    }
    const expectedDigest = sha256(expectedKey);
    return function gatewayAuth(req: AuthenticatedRequest, res: Response, next: NextFunction): void {
        const credential = extractCredential(req);
        if (credential === null) {
            options.onRejected?.({
                reason: 'missing',
                method: req.method,
                path: req.path,
                remoteAddress: req.socket.remoteAddress,
            });
            rejectUnauthorized(res);
            return;
        }
        if (credential.length > MAX_CREDENTIAL_LENGTH) {
            options.onRejected?.({
                reason: 'oversized',
                method: req.method,
                path: req.path,
                remoteAddress: req.socket.remoteAddress,
            });
            rejectUnauthorized(res);
            return;
        }
        const presentedDigest = sha256(credential);
        const authorized = timingSafeEqual(presentedDigest, expectedDigest);
        if (!authorized) {
            options.onRejected?.({
                reason: 'invalid',
                method: req.method,
                path: req.path,
                remoteAddress: req.socket.remoteAddress,
            });
            rejectUnauthorized(res);
            return;
        }
        if (options.tenantContext !== undefined) {
            req.valence = options.tenantContext;
        }
        next();
    };
}
