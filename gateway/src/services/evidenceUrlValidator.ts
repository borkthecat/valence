import { lookup } from 'node:dns/promises';
import { request as httpsRequest } from 'node:https';
import { isIP, type LookupFunction } from 'node:net';

export class EvidenceUrlError extends Error {
    public readonly status = 422;

    public constructor(message: string) {
        super(message);
        this.name = 'EvidenceUrlError';
    }
}

interface EvidenceReference {
    readonly url: string;
    readonly mimeType?: string;
}

interface EvidenceProfile {
    readonly images?: ReadonlyArray<{ readonly url: string; readonly mime_type: string }> | undefined;
    readonly links?: ReadonlyArray<{ readonly url: string; readonly media_type?: string | undefined }> | undefined;
}

interface EvidenceUrlOptions {
    readonly maxUrls: number;
    readonly timeoutMs: number;
    readonly resolve?: (hostname: string) => Promise<readonly string[]>;
    readonly request?: typeof fetch;
}

function isPrivateIpv4(address: string): boolean {
    const parts = address.split('.').map(Number);
    if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)) {
        return true;
    }
    const first = parts[0] ?? -1;
    const second = parts[1] ?? -1;
    return first === 0
        || first === 10
        || first === 127
        || (first === 100 && second >= 64 && second <= 127)
        || (first === 169 && second === 254)
        || (first === 172 && second >= 16 && second <= 31)
        || (first === 192 && second === 168)
        || (first === 198 && (second === 18 || second === 19))
        || first >= 224;
}

function isPrivateAddress(address: string): boolean {
    if (isIP(address) === 4) {
        return isPrivateIpv4(address);
    }
    if (isIP(address) !== 6) {
        return true;
    }
    const normalized = address.toLowerCase();
    if (normalized.startsWith('::ffff:')) {
        return isPrivateIpv4(normalized.slice(7));
    }
    return normalized === '::' || normalized === '::1' || normalized.startsWith('fc')
        || normalized.startsWith('fd') || /^fe[89ab]/.test(normalized);
}

async function defaultResolve(hostname: string): Promise<readonly string[]> {
    return (await lookup(hostname, { all: true, verbatim: true })).map((entry) => entry.address);
}

async function pinnedHead(
    url: URL,
    address: string,
    timeoutMs: number,
    accept: string,
): Promise<{ readonly ok: boolean; readonly status: number; readonly contentType?: string }> {
    return new Promise((resolve, reject) => {
        const family = isIP(address);
        const pinnedLookup: LookupFunction = (_hostname, options, callback) => {
            if (typeof options === 'object' && options.all) {
                callback(null, [{ address, family }]);
                return;
            }
            callback(null, address, family);
        };
        const request = httpsRequest(url, {
            method: 'HEAD',
            headers: { accept },
            servername: url.hostname,
            lookup: pinnedLookup,
        }, (response) => {
            response.resume();
            const contentType = response.headers['content-type']?.split(';', 1)[0]?.trim().toLowerCase();
            resolve({
                ok: response.statusCode !== undefined && response.statusCode >= 200 && response.statusCode < 300,
                status: response.statusCode ?? 0,
                ...(contentType === undefined ? {} : { contentType }),
            });
        });
        request.setTimeout(timeoutMs, () => request.destroy(new Error('evidence URL request timed out')));
        request.on('error', reject);
        request.end();
    });
}

async function verifyReference(reference: EvidenceReference, options: EvidenceUrlOptions): Promise<void> {
    const parsed = new URL(reference.url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || (parsed.port && parsed.port !== '443')) {
        throw new EvidenceUrlError('evidence URL must use HTTPS without credentials or a nonstandard port');
    }
    const addresses = await (options.resolve ?? defaultResolve)(parsed.hostname);
    if (addresses.length === 0 || addresses.some(isPrivateAddress)) {
        throw new EvidenceUrlError('evidence URL resolves to a private, reserved, or unavailable address');
    }
    const response = options.request === undefined
        ? await pinnedHead(parsed, addresses[0] as string, options.timeoutMs, reference.mimeType ?? '*/*')
        : await options.request(parsed, {
            method: 'HEAD',
            redirect: 'error',
            signal: AbortSignal.timeout(options.timeoutMs),
            headers: { accept: reference.mimeType ?? '*/*' },
        }).then((value) => {
            const contentType = value.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
            return {
                ok: value.ok,
                status: value.status,
                ...(contentType === undefined ? {} : { contentType }),
            };
        });
    if (!response.ok) {
        throw new EvidenceUrlError(`evidence URL returned HTTP ${response.status}`);
    }
    if (reference.mimeType !== undefined) {
        if (response.contentType !== reference.mimeType.toLowerCase()) {
            throw new EvidenceUrlError('image evidence content type does not match metadata');
        }
    }
}

export async function validateEvidenceUrls(
    profiles: readonly EvidenceProfile[],
    options: EvidenceUrlOptions,
): Promise<number> {
    const references = new Map<string, EvidenceReference>();
    for (const profile of profiles) {
        for (const image of profile.images ?? []) {
            references.set(image.url, { url: image.url, mimeType: image.mime_type });
        }
        for (const link of profile.links ?? []) {
            references.set(link.url, { url: link.url, ...(link.media_type ? { mimeType: link.media_type } : {}) });
        }
    }
    if (references.size > options.maxUrls) {
        throw new EvidenceUrlError(`live evidence validation is limited to ${options.maxUrls} unique URLs per request`);
    }
    const queue = [...references.values()];
    const workers = Array.from({ length: Math.min(8, queue.length) }, async () => {
        while (queue.length > 0) {
            const reference = queue.shift();
            if (reference !== undefined) {
                await verifyReference(reference, options);
            }
        }
    });
    await Promise.all(workers);
    return references.size;
}
