import { config } from '../config.js';
import { normalizeQuery } from '../ingest/transform/normalize.js';
import { embedInput } from './embedInput.js';
import { getEmbedder } from './embedder.js';
import { KeywordIndex, tokenize } from './keywordIndex.js';
import { loadIndex, vectorAt } from './vectorStore.js';

function dot(a, b) {
  let sum = 0;
  for (let i = 0; i < a.length; i += 1) sum += a[i] * b[i];
  return sum;
}

/** Fields exposed to callers (the desk's Knowledge tab and the LLM prompt use these). */
const toResult = (chunk) => ({
  id: chunk.id,
  source: chunk.source,
  docId: chunk.docId,
  title: chunk.title,
  headingPath: chunk.headingPath,
  url: chunk.url,
  category: chunk.category,
  audience: chunk.audience,
  text: chunk.text,
});

/**
 * Hybrid retriever: vector search and BM25 run side by side and are merged with reciprocal rank
 * fusion. `confidence` is the cosine similarity of the top result — the number the handoff policy
 * compares against its thresholds (calibrate them with `npm run eval`).
 */
export async function createRetriever() {
  const { manifest, chunks, vectors } = await loadIndex();
  if (!manifest) throw new Error('No index found. Run `npm run ingest` first.');

  const embedder = await getEmbedder();
  if (manifest.embedding.signature !== embedder.signature) {
    throw new Error(`The index was built with ${manifest.embedding.signature} but EMBEDDING_* now says ${embedder.signature}. Run \`npm run ingest\`.`);
  }

  const { dim } = manifest;
  const searchable = chunks.map((c) => !c.duplicateOf);
  const alsoIn = new Map();
  for (const chunk of chunks) {
    if (!chunk.duplicateOf) continue;
    if (!alsoIn.has(chunk.duplicateOf)) alsoIn.set(chunk.duplicateOf, []);
    alsoIn.get(chunk.duplicateOf).push({ source: chunk.source, docId: chunk.docId, title: chunk.title, url: chunk.url });
  }
  const keyword = new KeywordIndex(chunks.map((c, i) => (searchable[i] ? tokenize(embedInput(c)) : [])));

  /**
   * @param {string} query
   * @param {{ topK?: number, audience?: 'customer' | 'agent' | 'any', sources?: string[] | null, mode?: 'hybrid' | 'dense' | 'keyword' }} [options]
   */
  async function search(query, { topK = config.retrieval.topK, audience = 'customer', sources = null, mode = 'hybrid' } = {}) {
    const { candidates, rrfK } = config.retrieval;
    const text = normalizeQuery(query);
    const allowed = (i) => searchable[i] && (audience === 'any' || chunks[i].audience === audience) && (!sources || sources.includes(chunks[i].source));

    const queryVector = await embedder.embedQuery(text);
    const similarity = new Float32Array(chunks.length).fill(-Infinity);
    const pool = [];
    for (let i = 0; i < chunks.length; i += 1) {
      if (!allowed(i)) continue;
      similarity[i] = dot(queryVector, vectorAt(vectors, dim, i));
      pool.push(i);
    }
    const denseRanked = pool.sort((a, b) => similarity[b] - similarity[a]).slice(0, candidates);
    const keywordHits = keyword.search(tokenize(text), { limit: candidates, filter: allowed });
    const keywordScore = new Map(keywordHits.map((h) => [h.index, h.score]));

    let ranked;
    if (mode === 'dense') ranked = denseRanked;
    else if (mode === 'keyword') ranked = keywordHits.map((h) => h.index);
    else {
      const fused = new Map();
      denseRanked.forEach((index, rank) => fused.set(index, (fused.get(index) ?? 0) + 1 / (rrfK + rank + 1)));
      keywordHits.forEach(({ index }, rank) => fused.set(index, (fused.get(index) ?? 0) + 1 / (rrfK + rank + 1)));
      ranked = [...fused].sort((a, b) => b[1] - a[1]).map(([index]) => index);
    }

    const results = ranked.slice(0, topK).map((index) => ({
      ...toResult(chunks[index]),
      alsoIn: alsoIn.get(chunks[index].id) ?? [],
      similarity: Math.round(similarity[index] * 1000) / 1000,
      keywordScore: Math.round((keywordScore.get(index) ?? 0) * 100) / 100,
    }));

    return { query: text, confidence: results[0]?.similarity ?? 0, results };
  }

  return { search, manifest, size: searchable.filter(Boolean).length };
}
