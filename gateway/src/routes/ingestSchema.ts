import { z } from 'zod';

const PROFILE_LIMIT = 50_000;

const ProfileSchema = z.object({
    candidate_id: z.string().trim().min(1).max(128),
    age: z.number().finite(),
    retail_channel: z.string().trim().min(1).max(128),
    era: z.string().trim().min(1).max(128),
    raw_score: z.number().finite(),
}).strict();

const IngestionPayloadSchema = z.object({
    batch_id: z.string().trim().min(1).max(128),
    tenant_id: z.string().trim().min(1).max(128),
    profiles: z.array(ProfileSchema).min(1).max(PROFILE_LIMIT),
}).strict();

export type IngestionPayload = z.infer<typeof IngestionPayloadSchema>;

export function parseIngestionPayload(input: unknown): IngestionPayload {
    return IngestionPayloadSchema.parse(input);
}
