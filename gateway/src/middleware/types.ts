import type { Request } from 'express';
export interface TenantContext {
    readonly tenantId: string;
    readonly actorId: string;
    readonly scopes: readonly string[];
}
export interface AuthenticatedRequest extends Request {
    valence?: TenantContext;
}
