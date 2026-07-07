export interface GatewaySecrets {
  readonly upstreamApiKey: string;
  readonly gatewayApiKey: string;
  readonly jwtSecret?: string;
}

export interface SecretsProvider {
  loadGatewaySecrets(): GatewaySecrets;
}

export class EnvironmentSecretsProvider implements SecretsProvider {
  public loadGatewaySecrets(): GatewaySecrets {
    const jwtSecret = process.env['JWT_SECRET'];
    const secrets: GatewaySecrets = {
      upstreamApiKey: process.env['UPSTREAM_API_KEY'] ?? '',
      gatewayApiKey: process.env['GATEWAY_API_KEY'] ?? '',
      ...(jwtSecret ? { jwtSecret } : {}),
    };
    return secrets;
  }
}
