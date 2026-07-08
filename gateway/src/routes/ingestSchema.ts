import { z } from 'zod';

const PROFILE_LIMIT = 50_000;
const IMAGE_LIMIT = 12;
const LINK_LIMIT = 12;

const AttributeValueSchema = z.union([
    z.string().trim().max(1024),
    z.number().finite(),
    z.boolean(),
]);

const ImageEvidenceSchema = z.object({
    url: z.string().trim().url().max(2048).refine((value) => value.startsWith('https://'), {
        message: 'image url must use https',
    }),
    sha256: z.string().trim().regex(/^[a-fA-F0-9]{64}$/),
    mime_type: z.enum(['image/jpeg', 'image/png', 'image/webp']),
    source: z.string().trim().min(1).max(128),
    view: z.enum(['front', 'back', 'side', 'detail', 'packaging', 'label', 'other']).optional(),
    perceptual_hash: z.string().trim().regex(/^[a-fA-F0-9]{16}$/).optional(),
    quality_score: z.number().finite().min(0).max(1).optional(),
    width: z.number().int().positive().max(20_000).optional(),
    height: z.number().int().positive().max(20_000).optional(),
    bytes: z.number().int().positive().max(25_000_000).optional(),
}).strict();

const LinkEvidenceSchema = z.object({
    url: z.string().trim().url().max(2048).refine((value) => value.startsWith('https://'), {
        message: 'evidence link must use https',
    }),
    source: z.string().trim().min(1).max(128),
    media_type: z.string().trim().min(1).max(128).optional(),
    sha256: z.string().trim().regex(/^[a-fA-F0-9]{64}$/).optional(),
}).strict();

const ProfileSchema = z.object({
    candidate_id: z.string().trim().min(1).max(128),
    entity_type: z.string().trim().min(1).max(64).optional(),
    title: z.string().trim().min(1).max(512).optional(),
    description: z.string().trim().min(1).max(4096).optional(),
    age: z.number().finite(),
    retail_channel: z.string().trim().min(1).max(128),
    era: z.string().trim().min(1).max(128),
    colorway: z.string().trim().min(1).max(256).optional(),
    anniversary: z.boolean().optional(),
    raw_score: z.number().finite().min(0).max(100),
    attributes: z.record(z.string().trim().min(1).max(128), AttributeValueSchema).optional(),
    signals: z.record(z.string().trim().min(1).max(128), z.number().finite()).optional(),
    images: z.array(ImageEvidenceSchema).max(IMAGE_LIMIT).optional(),
    links: z.array(LinkEvidenceSchema).max(LINK_LIMIT).optional(),
}).strict();

const IngestionPayloadSchema = z.object({
    batch_id: z.string().trim().min(1).max(128),
    tenant_id: z.string().trim().min(1).max(128),
    profiles: z.array(ProfileSchema).min(1).max(PROFILE_LIMIT),
}).strict().superRefine((value, context) => {
    const seen = new Set<string>();
    value.profiles.forEach((profile, index) => {
        if (seen.has(profile.candidate_id)) {
            context.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['profiles', index, 'candidate_id'],
                message: 'candidate_id must be unique within a batch',
            });
        }
        seen.add(profile.candidate_id);
    });
});

export type IngestionPayload = z.infer<typeof IngestionPayloadSchema>;

export function parseIngestionPayload(input: unknown): IngestionPayload {
    return IngestionPayloadSchema.parse(input);
}
