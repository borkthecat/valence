import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

export interface GatewaySecrets {
  readonly upstreamApiKey: string;
  readonly gatewayApiKey: string;
  readonly jwtSecret?: string;
  readonly jwtPublicKeyPem?: string;
}

export interface SecretsProvider {
  loadGatewaySecrets(): GatewaySecrets;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined;
}

function normalizePem(value: string): string {
  return value.includes('\\n') ? value.replace(/\\n/g, '\n') : value;
}

export class EnvironmentSecretsProvider implements SecretsProvider {
  public loadGatewaySecrets(): GatewaySecrets {
    const jwtSecret = process.env['JWT_SECRET'];
    const jwtPublicKey = process.env['JWT_PUBLIC_KEY_PEM'];
    const secrets: GatewaySecrets = {
      upstreamApiKey: process.env['UPSTREAM_API_KEY'] ?? '',
      gatewayApiKey: process.env['GATEWAY_API_KEY'] ?? '',
      ...(jwtSecret ? { jwtSecret } : {}),
      ...(jwtPublicKey ? { jwtPublicKeyPem: normalizePem(jwtPublicKey) } : {}),
    };
    return secrets;
  }
}

export class FileSecretsProvider implements SecretsProvider {
  public constructor(private readonly path: string) {}

  public loadGatewaySecrets(): GatewaySecrets {
    const parsed = JSON.parse(readFileSync(resolve(this.path), 'utf8')) as Record<string, unknown>;
    const upstreamApiKey = optionalString(parsed['UPSTREAM_API_KEY']);
    const gatewayApiKey = optionalString(parsed['GATEWAY_API_KEY']);
    if (upstreamApiKey === undefined || gatewayApiKey === undefined) {
      throw new Error('secrets file must contain UPSTREAM_API_KEY and GATEWAY_API_KEY');
    }
    const jwtSecret = optionalString(parsed['JWT_SECRET']);
    const jwtPublicKeyPem = optionalString(parsed['JWT_PUBLIC_KEY_PEM']);
    return {
      upstreamApiKey,
      gatewayApiKey,
      ...(jwtSecret === undefined ? {} : { jwtSecret }),
      ...(jwtPublicKeyPem === undefined
        ? {}
        : { jwtPublicKeyPem: normalizePem(jwtPublicKeyPem) }),
    };
  }
}

export function createSecretsProvider(): SecretsProvider {
  const secretsFile = process.env['SECRETS_FILE_PATH'];
  return secretsFile === undefined || secretsFile.trim() === ''
    ? new EnvironmentSecretsProvider()
    : new FileSecretsProvider(secretsFile);
}
