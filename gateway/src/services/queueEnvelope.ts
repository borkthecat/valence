import { createHash } from 'node:crypto';

export type QueuedProfile = Readonly<Record<string, unknown>>;

export function buildQueuedMessages(
    tenantId: string,
    batchId: string,
    profiles: readonly QueuedProfile[],
): Array<{ readonly key: string; readonly value: string }> {
    const batchFingerprint = createHash('sha256').update(JSON.stringify(profiles)).digest('hex');
    return profiles.map((profile, profileIndex) => {
        const candidateId = String(profile['candidate_id'] ?? '');
        const messageId = createHash('sha256')
            .update(tenantId)
            .update('\0')
            .update(batchId)
            .update('\0')
            .update(batchFingerprint)
            .update('\0')
            .update(candidateId)
            .digest('hex');
        return {
            key: `${tenantId}:${batchId}:${batchFingerprint}`,
            value: JSON.stringify({
                message_id: messageId,
                batch_fingerprint: batchFingerprint,
                batch_id: batchId,
                batch_size: profiles.length,
                profile_index: profileIndex,
                tenant_id: tenantId,
                data: profile,
            }),
        };
    });
}
