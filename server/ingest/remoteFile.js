import { createHash } from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

/**
 * Cheap upstream version check: a HEAD request, no body. Hugging Face exposes the file's content
 * hash as X-Linked-ETag on its redirect; GitHub and most CDNs send ETag or Last-Modified.
 */
async function remoteVersion(url) {
  const res = await fetch(url, { method: 'HEAD', redirect: 'manual' });
  if (res.status >= 400) throw new Error(`HEAD ${url} → ${res.status}`);
  return res.headers.get('x-linked-etag') ?? res.headers.get('etag') ?? res.headers.get('last-modified');
}

async function download(url, dest) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`GET ${url} → ${res.status}`);
  await fsp.mkdir(path.dirname(dest), { recursive: true });
  const tmp = `${dest}.part`;
  await pipeline(Readable.fromWeb(res.body), fs.createWriteStream(tmp));
  await fsp.rename(tmp, dest);
}

async function hashFile(file) {
  const hash = createHash('sha256');
  await pipeline(fs.createReadStream(file), hash);
  return hash.digest('hex');
}

/**
 * Makes `dest` match the remote file, downloading only when the upstream version header changed.
 * "Changed" is then decided by a hash of the content, because some servers vary the header for
 * identical bytes (e.g. GitHub alternates weak and strong ETags). If the network is down but a
 * cached copy exists, the cached copy is used.
 *
 * @param {{ url: string, dest: string, previous?: { version?: string, contentHash?: string } }} options
 * @returns {Promise<{ changed: boolean, version: string | null, contentHash: string | null, offline?: boolean }>}
 */
export async function syncRemoteFile({ url, dest, previous = {} }) {
  const cached = fs.existsSync(dest);
  let version;
  try {
    version = await remoteVersion(url);
  } catch (error) {
    if (!cached) throw error;
    return { changed: false, version: previous.version ?? null, contentHash: previous.contentHash ?? null, offline: true };
  }

  if (cached && version && version === previous.version) {
    return { changed: false, version, contentHash: previous.contentHash ?? null };
  }
  await download(url, dest);
  const contentHash = await hashFile(dest);
  return { changed: contentHash !== previous.contentHash, version, contentHash };
}
