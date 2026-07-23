export interface ExpertRouteInput {
    readonly sourceId?: string;
}

export type GuardExecutionRoute = 'global-v6' | 'source-expert';
export type GuardAction = 'enforce' | 'review';

export interface GuardRouteDecision {
    readonly route: GuardExecutionRoute;
    readonly action: GuardAction;
}

export function routeForTrustedSource(input: ExpertRouteInput, expertSources: ReadonlySet<string>): GuardExecutionRoute {
    return input.sourceId !== undefined && expertSources.has(input.sourceId) ? 'source-expert' : 'global-v6';
}

export function decideGuardRoute(
    input: ExpertRouteInput,
    expertSources: ReadonlySet<string>,
    reviewSources: ReadonlySet<string>,
): GuardRouteDecision {
    const sourceId = input.sourceId;
    return {
        route: routeForTrustedSource(input, expertSources),
        action: sourceId !== undefined && reviewSources.has(sourceId) ? 'review' : 'enforce',
    };
}
