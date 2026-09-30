import { createHash } from 'node:crypto';
import path from 'node:path';
import { config } from '../config.js';
import { embedInput } from '../rag/embedInput.js';
import { getEmbedder } from '../rag/embedder.js';
import { appendCheckpoint, clearCheckpoint, loadCheckpoint, loadIndex, saveIndex, saveManifest, vectorAt } from '../rag/vectorStore.js';
import { ADAPTERS } from './adapters/index.js';
import { CHUNKER_VERSION, chunkMarkdown } from './transform/chunker.js';
import { NORMALIZER_VERSION, cleanText, indexForm } from './transform/normalize.js';

const sha = (text) => createHash('sha256').update(text).digest('hex');

/** Anything that changes how documents are parsed or chunked. A change forces sources to re-parse. */
function pipelineFingerprint(embedder) {
  const { minTokens, targetTokens, maxTokens } = config.chunking;
  return sha(JSON.stringify({ NORMALIZER_VERSION, CHUNKER_VERSION, minTokens, targetTokens, maxTokens, model: embedder.signature }));
}

async function processSource(adapter, { embedder, limit }) {
  const chunks = [];
  const documents = {};
  const context = { rawDir: path.join(config.paths.raw, adapter.id), contentDir: config.paths.content, limit };

  for await (const doc of adapter.documents(context)) {
    const title = cleanText(doc.title);
    const body = cleanText(doc.markdown, { boilerplate: adapter.boilerplate });
    if (!body) continue;
    documents[doc.id] = sha(`${title}\n${body}`);

    chunkMarkdown(body, { countTokens: embedder.countTokens, ...config.chunking }).forEach((piece, ordinal) => {
      const chunk = {
        id: `${adapter.id}:${doc.id}#${ordinal}`,
        source: adapter.id,
        docId: doc.id,
        ordinal,
        title,
        headingPath: piece.headingPath,
        url: doc.url,
        category: doc.category,
        audience: doc.audience,
        text: piece.text,
        tokens: piece.tokens,
      };
      chunk.key = sha(`${embedder.signature}\n${embedInput(chunk)}`);
      chunks.push(chunk);
    });
  }
  return { chunks, documents };
}

/**
 * Identical chunk text across documents (e.g. a FAQ block pasted into 130 payment articles) is kept
 * once for search. Duplicates stay in the index pointing at the canonical chunk, so the canonical
 * can list every article it belongs to, and nothing is lost if the canonical's article is removed.
 */
function markDuplicates(chunks) {
  const canonicalByText = new Map();
  let duplicates = 0;
  for (const chunk of chunks) {
    const textHash = sha(indexForm(chunk.text));
    const canonical = canonicalByText.get(textHash);
    if (canonical && canonical.docId !== chunk.docId) {
      chunk.duplicateOf = canonical.id;
      duplicates += 1;
    } else {
      delete chunk.duplicateOf;
      if (!canonical) canonicalByText.set(textHash, chunk);
    }
  }
  return duplicates;
}

function diffDocuments(previous = {}, current = {}) {
  const diff = { added: 0, changed: 0, removed: 0, unchanged: 0 };
  for (const [id, hash] of Object.entries(current)) {
    if (!(id in previous)) diff.added += 1;
    else if (previous[id] !== hash) diff.changed += 1;
    else diff.unchanged += 1;
  }
  diff.removed = Object.keys(previous).filter((id) => !(id in current)).length;
  return diff;
}

/**
 * Incremental ingestion. Change detection happens at three levels, cheapest first:
 *   1. source   — skipped while inside its refresh window, or when upstream reports the same version
 *   2. document — content hashes report added / changed / removed documents
 *   3. chunk    — a vector is reused whenever the exact embedding input was seen before
 *
 * @param {{ check?: boolean, rebuild?: boolean, reembed?: boolean, only?: string[], limit?: number, log?: Function }} options
 */
export async function runIngestion({ check = false, rebuild = false, reembed = false, only = null, limit = null, log = console.log } = {}) {
  const startedAt = Date.now();
  const embedder = await getEmbedder();
  const previous = await loadIndex();
  const fingerprint = pipelineFingerprint(embedder);
  const samePipeline = previous.manifest?.fingerprint === fingerprint;
  const now = Date.now();

  const unknown = config.ingest.sources.filter((id) => !ADAPTERS[id]);
  if (unknown.length) throw new Error(`Unknown source(s) in INGEST_SOURCES: ${unknown.join(', ')}. Known: ${Object.keys(ADAPTERS).join(', ')}`);
  // Carrying unselected sources over would mix vectors from old and new settings in one index.
  if (only && previous.manifest && !samePipeline) {
    throw new Error('Model, normalizer or chunker settings changed since the last build, so every source must be rebuilt. Run without --source.');
  }

  const sourceReports = [];
  const nextSources = {};
  const nextDocuments = {};
  let allChunks = [];
  let anythingProcessed = false;

  for (const sourceId of config.ingest.sources) {
    const adapter = ADAPTERS[sourceId];
    const state = previous.manifest?.sources?.[sourceId];
    const previousChunks = previous.chunks.filter((c) => c.source === sourceId);
    const reusable = samePipeline && state && state.limit === (limit ?? null) && !rebuild;
    const reuse = (reason) => {
      allChunks.push(...previousChunks);
      nextDocuments[sourceId] = previous.documents[sourceId] ?? {};
      sourceReports.push({ source: sourceId, action: 'kept', reason, chunks: previousChunks.length });
    };

    // Sources not selected with --source are carried over untouched (or left out if never ingested).
    if (only && !only.includes(sourceId)) {
      if (state) {
        nextSources[sourceId] = state;
        reuse('not selected');
      } else sourceReports.push({ source: sourceId, action: 'skipped', reason: 'not selected, never ingested', chunks: 0 });
      continue;
    }

    // 1a. Inside the refresh window: don't even ask upstream.
    const refreshMs = (config.ingest.refreshMinutes[sourceId] ?? 0) * 60_000;
    if (reusable && !check && refreshMs > 0 && now - state.checkedAt < refreshMs) {
      nextSources[sourceId] = state;
      reuse(`checked ${Math.round((now - state.checkedAt) / 60_000)} min ago (refresh every ${refreshMs / 60_000} min)`);
      continue;
    }

    // 1b. Ask upstream for its version; download only if it changed.
    log(`[${sourceId}] checking upstream…`);
    const sync = await adapter.sync({
      rawDir: path.join(config.paths.raw, sourceId),
      contentDir: config.paths.content,
      previous: state ?? {},
    });
    if (reusable && !sync.changed) {
      nextSources[sourceId] = { ...state, version: sync.version, contentHash: sync.contentHash ?? state.contentHash, checkedAt: now };
      reuse(sync.offline ? 'upstream unreachable — using cached copy' : 'unchanged upstream');
      continue;
    }

    // 2. Parse → normalize → chunk.
    const why = !state
      ? 'first ingestion'
      : sync.changed
        ? 'changed upstream'
        : rebuild
          ? '--rebuild'
          : !samePipeline
            ? 'normalizer, chunker or model settings changed'
            : 'document limit changed';
    log(`[${sourceId}] ${why} — processing documents…`);
    const { chunks, documents } = await processSource(adapter, { embedder, limit });
    allChunks.push(...chunks);
    nextDocuments[sourceId] = documents;
    nextSources[sourceId] = {
      version: sync.version,
      contentHash: sync.contentHash ?? null,
      checkedAt: now,
      processedAt: now,
      limit: limit ?? null,
      documents: Object.keys(documents).length,
      chunks: chunks.length,
    };
    sourceReports.push({ source: sourceId, action: 'processed', documents: diffDocuments(previous.documents[sourceId], documents), chunks: chunks.length });
    anythingProcessed = true;
  }

  const removedSources = Object.keys(previous.manifest?.sources ?? {}).filter((id) => !(id in nextSources));
  if (!anythingProcessed && !removedSources.length && samePipeline && !reembed) {
    await saveManifest({ ...previous.manifest, sources: nextSources });
    return { sources: sourceReports, removedSources, embedded: 0, reused: previous.chunks.length, removedChunks: 0, total: previous.chunks.length, durationMs: Date.now() - startedAt, wrote: 'manifest only' };
  }

  // 3. Reuse vectors by key; embed only what's new.
  const duplicates = markDuplicates(allChunks);
  const dim = previous.manifest?.dim;
  const previousRowByKey = new Map();
  if (!reembed && dim) {
    previous.chunks.forEach((chunk, row) => {
      if (!chunk.duplicateOf) previousRowByKey.set(chunk.key, row); // a duplicate's row holds its canonical's vector
    });
  }

  // Vectors from an interrupted earlier run (see appendCheckpoint below).
  if (reembed) await clearCheckpoint();
  const checkpoint = reembed ? new Map() : await loadCheckpoint(embedder.dim);

  const vectorByKey = new Map();
  const toEmbed = [];
  let resumed = 0;
  for (const chunk of allChunks) {
    if (chunk.duplicateOf || vectorByKey.has(chunk.key)) continue;
    const row = previousRowByKey.get(chunk.key);
    if (row !== undefined) vectorByKey.set(chunk.key, vectorAt(previous.vectors, dim, row));
    else if (checkpoint.has(chunk.key)) {
      vectorByKey.set(chunk.key, checkpoint.get(chunk.key));
      resumed += 1;
    } else toEmbed.push(chunk);
  }
  const reused = vectorByKey.size - resumed;

  if (toEmbed.length) {
    log(`Embedding ${toEmbed.length} new or changed chunks (${reused} reused${resumed ? `, ${resumed} resumed from an interrupted run` : ''})…`);
    // Batches are padded to their longest input, so batching similar lengths together avoids
    // spending most of the compute on padding.
    toEmbed.sort((a, b) => a.tokens - b.tokens);
    const embedStart = Date.now();
    for (let i = 0; i < toEmbed.length; i += config.embedding.batchSize) {
      const batch = toEmbed.slice(i, i + config.embedding.batchSize);
      const vectors = await embedder.embedDocuments(batch.map(embedInput));
      batch.forEach((chunk, j) => vectorByKey.set(chunk.key, vectors[j]));
      // Persist as we go: if the run is interrupted, the next one picks up from here.
      await appendCheckpoint(batch.map((c) => c.key), vectors);
      const done = Math.min(i + batch.length, toEmbed.length);
      const rate = done / ((Date.now() - embedStart) / 1000);
      if (done === toEmbed.length || (i / config.embedding.batchSize) % 25 === 0) {
        log(`  ${done}/${toEmbed.length} (${rate.toFixed(1)}/s, ~${Math.ceil((toEmbed.length - done) / rate)}s left)`);
      }
    }
  }

  const newDim = embedder.dim;
  const byId = new Map(allChunks.map((c) => [c.id, c]));
  const vectors = new Float32Array(allChunks.length * newDim);
  allChunks.forEach((chunk, row) => {
    const owner = chunk.duplicateOf ? byId.get(chunk.duplicateOf) : chunk;
    vectors.set(vectorByKey.get(owner.key), row * newDim);
  });

  const currentKeys = new Set(allChunks.map((c) => c.key));
  const removedChunks = previous.chunks.filter((c) => !currentKeys.has(c.key)).length;

  await saveIndex({
    manifest: {
      formatVersion: 1,
      builtAt: new Date(now).toISOString(),
      fingerprint,
      embedding: { model: embedder.model, signature: embedder.signature },
      dim: newDim,
      normalizerVersion: NORMALIZER_VERSION,
      chunkerVersion: CHUNKER_VERSION,
      chunking: config.chunking,
      count: allChunks.length,
      duplicates,
      sources: nextSources,
    },
    chunks: allChunks,
    vectors,
    documents: nextDocuments,
  });
  await clearCheckpoint(); // everything is in the index now

  return {
    sources: sourceReports,
    removedSources,
    embedded: toEmbed.length,
    reused,
    resumed,
    duplicates,
    removedChunks,
    total: allChunks.length,
    durationMs: Date.now() - startedAt,
    wrote: 'full index',
  };
}
