import { z } from 'zod';
import { createSecretsProvider } from './secrets';
export const SECURITY_MODES = ['FAIL_CLOSED', 'FAIL_OPEN'] as const;
export type SecurityMode = (typeof SECURITY_MODES)[number];
export const AUTH_MODES = ['api_key', 'jwt'] as const;
export type AuthMode = (typeof AUTH_MODES)[number];
export const JWT_ALGORITHMS = ['HS256', 'RS256'] as const;
export type JwtAlgorithm = (typeof JWT_ALGORITHMS)[number];
export const ENTERPRISE_INGEST_AUTH_MODES = ['jwks', 'api_key'] as const;
export const EVIDENCE_URL_VALIDATION_MODES = ['syntax', 'live'] as const;
export type EnterpriseIngestAuthMode = (typeof ENTERPRISE_INGEST_AUTH_MODES)[number];
const MIN_UPSTREAM_KEY_LENGTH = 16;
const MIN_GATEWAY_KEY_LENGTH = 32;
const MIN_JWT_SECRET_LENGTH = 32;
const portSchema = z.coerce
    .number({ invalid_type_error: 'port must be a numeric TCP port' })
    .int('port must be an integer')
    .min(1, 'port must be >= 1')
    .max(65535, 'port must be <= 65535');
const secureServiceUrl = z.string().trim().url().refine((value) => {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' || (parsed.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname));
}, 'service URL must use HTTPS, except for loopback development services');
const environmentSchema = z.object({
    PORT: portSchema.default(8443),
    GATEWAY_PORT: portSchema.optional(),
    MAX_PAYLOAD_KB: z.coerce
        .number({ invalid_type_error: 'MAX_PAYLOAD_KB must be numeric' })
        .int('MAX_PAYLOAD_KB must be an integer')
        .min(1, 'MAX_PAYLOAD_KB must be >= 1')
        .max(65536, 'MAX_PAYLOAD_KB must be <= 65536')
        .default(512),
    UPSTREAM_PROVIDER_URL: z
        .string()
        .trim()
        .url('UPSTREAM_PROVIDER_URL must be a valid absolute URL')
        .refine((value) => {
        const parsed = new URL(value);
        if (parsed.protocol === 'https:') {
            return true;
        }
        return (parsed.protocol === 'http:' &&
            ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname));
    }, {
        message: 'UPSTREAM_PROVIDER_URL must use https:// (http:// is permitted only for loopback hosts)',
    }),
    UPSTREAM_API_KEY: z
        .string()
        .trim()
        .min(MIN_UPSTREAM_KEY_LENGTH, `UPSTREAM_API_KEY must be at least ${MIN_UPSTREAM_KEY_LENGTH} characters`),
    GATEWAY_API_KEY: z
        .string()
        .trim()
        .min(MIN_GATEWAY_KEY_LENGTH, `GATEWAY_API_KEY must be at least ${MIN_GATEWAY_KEY_LENGTH} characters (require high-entropy keys)`),
    SECURITY_MODE: z.enum(SECURITY_MODES).default('FAIL_CLOSED'),
    AUTH_MODE: z.enum(AUTH_MODES).default('api_key'),
    JWT_ALGORITHM: z.enum(JWT_ALGORITHMS).default('HS256'),
    JWT_SECRET: z.string().trim().min(MIN_JWT_SECRET_LENGTH).optional(),
    JWT_PUBLIC_KEY_PEM: z.string().trim().min(64).optional(),
    JWKS_URI: z.string().trim().url().optional(),
    ENTERPRISE_INGEST_AUTH_MODE: z.enum(ENTERPRISE_INGEST_AUTH_MODES).default('jwks'),
    JWT_REQUIRED_SCOPE: z.string().trim().min(1).default('valence:proxy'),
    JWT_ISSUER: z.string().trim().min(1).optional(),
    JWT_AUDIENCE: z.string().trim().min(1).optional(),
    KAFKA_BOOTSTRAP_SERVERS: z.string().trim().min(1).default('kafka:9092'),
    KAFKA_INGEST_TOPIC: z.string().trim().min(1).default('valence-raw-profiles'),
    REDIS_URL: z.string().trim().url().optional(),
    PII_CLASSIFIER_URL: secureServiceUrl.optional(),
    PII_CLASSIFIER_API_KEY: z.string().trim().min(16).optional(),
    GUARD_MODEL_URL: secureServiceUrl.optional(),
    GUARD_MODEL_PATH: z.string().trim().min(1).optional(),
    GUARD_MODEL_SHA256: z.string().trim().regex(/^[a-f0-9]{64}$/).optional(),
    GUARD_MODEL_API_KEY: z.string().trim().min(16).optional(),
    MODEL_SERVICE_TIMEOUT_MS: z.coerce.number().int().min(100).max(30000).default(3000),
    EVIDENCE_URL_VALIDATION: z.enum(EVIDENCE_URL_VALIDATION_MODES).default('syntax'),
    EVIDENCE_URL_TIMEOUT_MS: z.coerce.number().int().min(100).max(10000).default(3000),
    MAX_LIVE_EVIDENCE_URLS: z.coerce.number().int().min(1).max(1000).default(100),
    RATE_LIMIT_WINDOW_MS: z.coerce
        .number({ invalid_type_error: 'RATE_LIMIT_WINDOW_MS must be numeric' })
        .int('RATE_LIMIT_WINDOW_MS must be an integer')
        .min(1000, 'RATE_LIMIT_WINDOW_MS must be >= 1000')
        .max(3600000, 'RATE_LIMIT_WINDOW_MS must be <= 3600000')
        .default(60000),
    RATE_LIMIT_MAX_REQUESTS: z.coerce
        .number({ invalid_type_error: 'RATE_LIMIT_MAX_REQUESTS must be numeric' })
        .int('RATE_LIMIT_MAX_REQUESTS must be an integer')
        .min(1, 'RATE_LIMIT_MAX_REQUESTS must be >= 1')
        .max(100000, 'RATE_LIMIT_MAX_REQUESTS must be <= 100000')
        .default(120),
    AUDIT_LOG_PATH: z.string().trim().min(1).default('audit/valence-audit.log'),
    NODE_ENV: z
        .enum(['development', 'test', 'production'])
        .default('production'),
}).superRefine((value, ctx) => {
    if (value.AUTH_MODE === 'jwt' &&
        value.JWT_ALGORITHM === 'HS256' &&
        value.JWT_SECRET === undefined) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['JWT_SECRET'],
            message: 'JWT_SECRET is required when AUTH_MODE=jwt and JWT_ALGORITHM=HS256',
        });
    }
    if (value.AUTH_MODE === 'jwt' &&
        value.JWT_ALGORITHM === 'RS256' &&
        value.JWT_PUBLIC_KEY_PEM === undefined) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['JWT_PUBLIC_KEY_PEM'],
            message: 'JWT_PUBLIC_KEY_PEM is required when AUTH_MODE=jwt and JWT_ALGORITHM=RS256',
        });
    }
    if (value.GUARD_MODEL_URL !== undefined && value.GUARD_MODEL_PATH !== undefined) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['GUARD_MODEL_PATH'],
            message: 'configure either GUARD_MODEL_URL or GUARD_MODEL_PATH, not both',
        });
    }
    if (value.GUARD_MODEL_PATH !== undefined && value.GUARD_MODEL_SHA256 === undefined) {
        ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ['GUARD_MODEL_SHA256'],
            message: 'GUARD_MODEL_SHA256 is required with GUARD_MODEL_PATH',
        });
    }
});
export type Environment = Readonly<z.infer<typeof environmentSchema>>;
function formatValidationIssues(error: z.ZodError): string {
    return error.issues
        .map((issue) => {
        const variable = issue.path.join('.') || '(root)';
        return `  - ${variable}: ${issue.message}`;
    })
        .join('\n');
}
function loadEnvironment(): Environment {
    const secrets = createSecretsProvider().loadGatewaySecrets();
    const result = environmentSchema.safeParse({
        ...process.env,
        UPSTREAM_API_KEY: secrets.upstreamApiKey,
        GATEWAY_API_KEY: secrets.gatewayApiKey,
        ...(secrets.jwtSecret === undefined ? {} : { JWT_SECRET: secrets.jwtSecret }),
        ...(secrets.jwtPublicKeyPem === undefined
            ? {}
            : { JWT_PUBLIC_KEY_PEM: secrets.jwtPublicKeyPem }),
        ...(secrets.piiClassifierApiKey === undefined
            ? {}
            : { PII_CLASSIFIER_API_KEY: secrets.piiClassifierApiKey }),
        ...(secrets.guardModelApiKey === undefined
            ? {}
            : { GUARD_MODEL_API_KEY: secrets.guardModelApiKey }),
    });
    if (!result.success) {
        process.stderr.write([
            '[valence] FATAL: environment validation failed.',
            '[valence] The gateway refuses to start with an invalid security configuration (fail-closed boot).',
            formatValidationIssues(result.error),
            '',
        ].join('\n'));
        process.exit(1);
    }
    if (result.data.SECURITY_MODE === 'FAIL_OPEN') {
        process.stderr.write('[valence] WARNING: SECURITY_MODE=FAIL_OPEN - scanner failures will forward traffic UNSCANNED. Never use this posture in production.\n');
    }
    const effective = {
        ...result.data,
        PORT: result.data.GATEWAY_PORT ?? result.data.PORT,
    };
    return Object.freeze(effective);
}
export const environment: Environment = loadEnvironment();
