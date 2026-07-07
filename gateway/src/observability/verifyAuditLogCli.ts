import { verifyAuditLog } from './auditLog';

function main(argv: readonly string[]): void {
  const path = argv[2];
  if (path === undefined || path.trim() === '') {
    process.stderr.write('usage: node dist/observability/verifyAuditLogCli.js <audit-log-path>\n');
    process.exit(2);
  }

  const result = verifyAuditLog(path);
  if (!result.valid) {
    process.stderr.write(
      `audit log invalid after ${result.records} record(s): ${result.error ?? 'unknown error'}\n`,
    );
    process.exit(1);
  }

  process.stdout.write(`audit log valid: ${result.records} record(s)\n`);
}

if (require.main === module) {
  main(process.argv);
}
