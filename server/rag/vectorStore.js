import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from '../config.js';

// A small file-based vector store — enough for tens of thousands of chunks with brute-force search.
// Layout (data/index/):
//   manifest.json   model, dimensions, pipeline fingerprint, per-source sync state
//   chunks.jsonl    one chunk per line (text + metadata), row i ↔ vector i
//   vectors.f32     Float32 little-endian, row-major, `count × dim`
//   documents.json  per-source { docId: contentHash } for change reports
//
// Swap for pgvector/Qdrant/LanceDB later by keeping load()/save() the same shape.

const FILES = { manifest: 'manifest.json', chunks: 'chunks.jsonl', vectors: 'vectors.f32', documents: 'documents.json' };
const file = (name) => path.join(config.paths.index, FILES[name]);

async function readOptional(name, encoding) {
  try {
    return await fs.readFile(file(name), encoding);
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

/** Write to a temp file and rename, so a crash mid-write never leaves a half-written index. */
async function writeAtomic(name, data) {
  const target = file(name);
  await fs.writeFile(`${target}.tmp`, data);
  await fs.rename(`${target}.tmp`, target);
}

export async function loadIndex() {
  const manifestRaw = await readOptional('manifest', 'utf8');
  if (!manifestRaw) return { manifest: null, chunks: [], vectors: new Float32Array(0), documents: {} };

  const manifest = JSON.parse(manifestRaw);
  const chunks = (await readOptional('chunks', 'utf8') ?? '').split('\n').filter(Boolean).map(JSON.parse);
  const buffer = (await readOptional('vectors')) ?? Buffer.alloc(0);
  // Copy into a fresh ArrayBuffer: a Buffer's byteOffset isn't guaranteed to be 4-byte aligned.
  const vectors = new Float32Array(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength));
  const documents = JSON.parse((await readOptional('documents', 'utf8')) ?? '{}');

  if (chunks.length * manifest.dim !== vectors.length) {
    throw new Error(`Index is inconsistent (${chunks.length} chunks, ${vectors.length / manifest.dim} vectors). Re-run with --force.`);
  }
  return { manifest, chunks, vectors, documents };
}

/** Row `i` as a Float32Array view (no copy). */
export const vectorAt = (vectors, dim, i) => vectors.subarray(i * dim, (i + 1) * dim);

export async function saveIndex({ manifest, chunks, vectors, documents }) {
  await fs.mkdir(config.paths.index, { recursive: true });
  // Data files first, manifest last: the manifest is what marks the new index as complete.
  await writeAtomic('chunks', chunks.map((c) => JSON.stringify(c)).join('\n'));
  await writeAtomic('vectors', Buffer.from(vectors.buffer, vectors.byteOffset, vectors.byteLength));
  await writeAtomic('documents', JSON.stringify(documents));
  await writeAtomic('manifest', JSON.stringify(manifest, null, 2));
}

// ─── Checkpoint ─────────────────────────────────────────────────────────────
// Vectors are appended here batch by batch while embedding, so an interrupted build (Ctrl+C, crash,
// power loss) resumes where it stopped instead of re-embedding everything. Cleared after a save.
const CHECKPOINT_KEYS = () => path.join(config.paths.index, 'checkpoint.keys');
const CHECKPOINT_VECTORS = () => path.join(config.paths.index, 'checkpoint.f32');

export async function appendCheckpoint(keys, vectors) {
  await fs.mkdir(config.paths.index, { recursive: true });
  const rows = new Float32Array(vectors.reduce((n, v) => n + v.length, 0));
  let offset = 0;
  for (const vector of vectors) {
    rows.set(vector, offset);
    offset += vector.length;
  }
  // Vectors first, keys second: a crash in between leaves extra vectors, which are ignored.
  await fs.appendFile(CHECKPOINT_VECTORS(), Buffer.from(rows.buffer));
  await fs.appendFile(CHECKPOINT_KEYS(), `${keys.join('\n')}\n`);
}

/** @returns {Promise<Map<string, Float32Array>>} */
export async function loadCheckpoint(dim) {
  try {
    const keys = (await fs.readFile(CHECKPOINT_KEYS(), 'utf8')).split('\n').filter(Boolean);
    const buffer = await fs.readFile(CHECKPOINT_VECTORS());
    const all = new Float32Array(buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength - (buffer.byteLength % 4)));
    // More vectors than keys means the last write was cut short — trust only rows with a key.
    const usable = Math.min(keys.length, Math.floor(all.length / dim));
    return new Map(keys.slice(0, usable).map((key, i) => [key, all.slice(i * dim, (i + 1) * dim)]));
  } catch (error) {
    if (error.code === 'ENOENT') return new Map();
    throw error;
  }
}

export async function clearCheckpoint() {
  await fs.rm(CHECKPOINT_KEYS(), { force: true });
  await fs.rm(CHECKPOINT_VECTORS(), { force: true });
}

export async function saveManifest(manifest) {
  await fs.mkdir(config.paths.index, { recursive: true });
  await writeAtomic('manifest', JSON.stringify(manifest, null, 2));
}
