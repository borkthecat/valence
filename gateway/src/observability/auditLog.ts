import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { appendFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

export type AuditEvent = Readonly<Record<string, string | number | boolean | null>>;

interface AuditRecord {
  readonly sequence: number;
  readonly timestamp: string;
  readonly previous_hash: string;
  readonly event: AuditEvent;
  readonly hash: string;
}

const GENESIS_HASH = '0'.repeat(64);

function digest(sequence: number, timestamp: string, previousHash: string, event: AuditEvent): string {
  return createHash('sha256')
    .update(JSON.stringify({ sequence, timestamp, previous_hash: previousHash, event }))
    .digest('hex');
}

function readTail(path: string): { sequence: number; hash: string } {
  if (!existsSync(path)) {
    return { sequence: 0, hash: GENESIS_HASH };
  }
  const lines = readFileSync(path, 'utf8').trim().split(/\r?\n/).filter(Boolean);
  const last = lines.at(-1);
  if (last === undefined) {
    return { sequence: 0, hash: GENESIS_HASH };
  }
  const parsed = JSON.parse(last) as Pick<AuditRecord, 'sequence' | 'hash'>;
  if (!Number.isInteger(parsed.sequence) || typeof parsed.hash !== 'string') {
    throw new Error('audit log tail is malformed');
  }
  return { sequence: parsed.sequence, hash: parsed.hash };
}

export class HashChainedAuditLog {
  private previousHash: string;
  private sequence: number;
  private queue: Promise<void> = Promise.resolve();
  private failed: Error | null = null;

  public constructor(private readonly path: string) {
    const absolute = resolve(path);
    mkdirSync(dirname(absolute), { recursive: true, mode: 0o700 });
    const tail = readTail(absolute);
    this.path = absolute;
    this.sequence = tail.sequence;
    this.previousHash = tail.hash;
  }

  public record(event: AuditEvent): void {
    this.sequence += 1;
    const timestamp = new Date().toISOString();
    const previousHash = this.previousHash;
    const hash = digest(this.sequence, timestamp, previousHash, event);
    this.previousHash = hash;
    const record: AuditRecord = {
      sequence: this.sequence,
      timestamp,
      previous_hash: previousHash,
      event,
      hash,
    };
    this.queue = this.queue
      .then(() => appendFile(this.path, `${JSON.stringify(record)}\n`, { mode: 0o600 }))
      .catch((error: unknown) => {
        this.failed = error instanceof Error ? error : new Error(String(error));
      });
  }

  public async flush(): Promise<void> {
    await this.queue;
    if (this.failed !== null) {
      throw this.failed;
    }
  }
}

export function createAuditLog(path: string): HashChainedAuditLog | null {
  return path.trim().toLowerCase() === 'off' ? null : new HashChainedAuditLog(path);
}
