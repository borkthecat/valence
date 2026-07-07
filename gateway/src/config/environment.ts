/**
 * Valence Gateway - Environment Configuration Boundary
 *
 * Single source of truth for all process-level configuration. Every value
 * consumed anywhere in the gateway MUST flow through this module; direct
 * `process.env` access outside this file is a lint-enforced violation.
 *
 * Validation is fail-fast: an invalid or incomplete environment terminates
 * the process with exit code 1 before the proxy can bind a socket. A gateway
 * that boots with a malformed security posture is worse than one that does
 * not boot at all.
 */

import { z } from 'zod';

/**
 * Security posture of the gateway when an internal control (scanner,
 * classifier, vault) errors at request time:
 *
 * - FAIL_CLOSED: the request is rejected. This is the only posture
 *   appropriate for production zero-trust deployments.
 * - FAIL_OPEN:   the request is forwarded unscanned. Permitted solely for
 *   controlled evaluation environments; the gateway logs a persistent
 *   warning banner when this mode is active.
 */
export const SECURITY_MODES = ['FAIL_CLOSED', 'FAIL_OPEN'] as const;
export type SecurityMode = (typeof SECURITY_MODES)[number];

const MIN_UPSTREAM_KEY_LENGTH = 16;
const MIN_GATEWAY_KEY_LENGTH = 32;

const environmentSchema = z.object({
  /** TCP port the gateway listens on. */
  PORT: z.coerce
    .number({ invalid_type_error: 'PORT must be a numeric TCP port' })
    .int('PORT must be an integer')
    .min(1, 'PORT must be >= 1')
    .max(65535, 'PORT must be <= 65535')
    .default(8443),

  /** Base URL of the upstream LLM provider (e.g. https://api.anthropic.com). */
  UPSTREAM_PROVIDER_URL: z
    .string()
    .trim()
    .url('UPSTREAM_PROVIDER_URL must be a valid absolute URL')
    .refine(
      (value) => {
        const parsed = new URL(value);
        if (parsed.protocol === 'https:') {
          return true;
        }
        // Plaintext HTTP is tolerated only for loopback targets so that
        // local integration harnesses can stub the upstream provider.
        return (
          parsed.protocol === 'http:' &&
          ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)
        );
      },
      {
        message:
          'UPSTREAM_PROVIDER_URL must use https:// (http:// is permitted only for loopback hosts)',
      },
    ),

  /** Credential presented by the gateway to the upstream provider. */
  UPSTREAM_API_KEY: z
    .string()
    .trim()
    .min(
      MIN_UPSTREAM_KEY_LENGTH,
      `UPSTREAM_API_KEY must be at least ${MIN_UPSTREAM_KEY_LENGTH} characters`,
    ),

  /** Credential clients must present to the gateway itself. */
  GATEWAY_API_KEY: z
    .string()
    .trim()
    .min(
      MIN_GATEWAY_KEY_LENGTH,
      `GATEWAY_API_KEY must be at least ${MIN_GATEWAY_KEY_LENGTH} characters (require high-entropy keys)`,
    ),

  /** Fail-closed / fail-open posture. Defaults to the safe posture. */
  SECURITY_MODE: z.enum(SECURITY_MODES).default('FAIL_CLOSED'),

  NODE_ENV: z
    .enum(['development', 'test', 'production'])
    .default('production'),
});

export type Environment = Readonly<z.infer<typeof environmentSchema>>;

/**
 * Formats Zod issues for operator-facing stderr output. Only variable names
 * and constraint descriptions are emitted - never the offending values, so
 * a mistyped secret cannot leak into logs or crash reports.
 */
function formatValidationIssues(error: z.ZodError): string {
  return error.issues
    .map((issue) => {
      const variable = issue.path.join('.') || '(root)';
      return `  - ${variable}: ${issue.message}`;
    })
    .join('\n');
}

function loadEnvironment(): Environment {
  const result = environmentSchema.safeParse(process.env);

  if (!result.success) {
    process.stderr.write(
      [
        '[valence] FATAL: environment validation failed.',
        '[valence] The gateway refuses to start with an invalid security configuration (fail-closed boot).',
        formatValidationIssues(result.error),
        '',
      ].join('\n'),
    );
    process.exit(1);
  }

  if (result.data.SECURITY_MODE === 'FAIL_OPEN') {
    process.stderr.write(
      '[valence] WARNING: SECURITY_MODE=FAIL_OPEN - scanner failures will forward traffic UNSCANNED. Never use this posture in production.\n',
    );
  }

  return Object.freeze(result.data);
}

/**
 * Validated, frozen configuration. Importing this module in an invalid
 * environment terminates the process; downstream code may therefore treat
 * every field as present and well-formed.
 */
export const environment: Environment = loadEnvironment();
