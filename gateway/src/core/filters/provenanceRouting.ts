import type { GuardPolicy } from './injectionShield';

export const VALENCE_BOUNDARIES = [
    'user_session',
    'compiled_article',
    'raw_source',
    'retrieved_document',
    'profile_description',
    'ocr_text',
    'secret_store',
] as const;

export type ValenceBoundary = (typeof VALENCE_BOUNDARIES)[number];

export interface ProvenanceRouteInput {
    readonly boundary: ValenceBoundary;
    readonly contentionScore?: number;
}

export interface ProvenanceGuardRoute {
    readonly policy: GuardPolicy;
    readonly minimumModelScore: number;
}

const ROUTES: Record<ValenceBoundary, ProvenanceGuardRoute> = {
    user_session: { policy: 'direct', minimumModelScore: 0.85 },
    compiled_article: { policy: 'direct', minimumModelScore: 0.85 },
    raw_source: { policy: 'indirect', minimumModelScore: 0.35 },
    retrieved_document: { policy: 'indirect', minimumModelScore: 0.40 },
    profile_description: { policy: 'indirect', minimumModelScore: 0.45 },
    ocr_text: { policy: 'indirect', minimumModelScore: 0.35 },
    secret_store: { policy: 'secret', minimumModelScore: 0.35 },
};

function clamp(value: number, low: number, high: number): number {
    return Math.min(high, Math.max(low, value));
}

export function routeForProvenance(input: ProvenanceRouteInput): ProvenanceGuardRoute {
    const base = ROUTES[input.boundary];
    const contention = clamp(input.contentionScore ?? 0, 0, 1);
    return {
        policy: base.policy,
        minimumModelScore: Number(clamp(base.minimumModelScore - contention * 0.25, 0.25, 0.95).toFixed(4)),
    };
}
