import { env, pipeline } from '@huggingface/transformers';
import { config } from '../config.js';

let instance = null;

async function createLocalEmbedder() {
  const { model, dtype, pooling, queryPrefix } = config.embedding;
  env.cacheDir = config.paths.models; // model files download here once, then load from disk
  const extractor = await pipeline('feature-extraction', model, { dtype });

  const embed = async (texts) => {
    const output = await extractor(texts, { pooling, normalize: true });
    const [rows, dim] = output.dims;
    return Array.from({ length: rows }, (_, i) => output.data.slice(i * dim, (i + 1) * dim));
  };

  const [probe] = await embed(['dimension probe']);

  return {
    model,
    dim: probe.length,
    /** Identifies everything that changes a document vector; part of each chunk's cache key. */
    signature: `${model}|${dtype}|${pooling}`,
    countTokens: (text) => extractor.tokenizer.encode(text).length,
    /** @returns {Promise<Float32Array[]>} unit-length vectors */
    embedDocuments: embed,
    /** Queries get the model's retrieval instruction; documents don't (per BGE usage notes). */
    embedQuery: async (text) => (await embed([queryPrefix ? `${queryPrefix} ${text}` : text]))[0],
  };
}

/** Lazily-created singleton — loading the model takes a few seconds. */
export function getEmbedder() {
  if (config.embedding.provider !== 'local') {
    throw new Error(`EMBEDDING_PROVIDER="${config.embedding.provider}" is not supported yet. Use "local" (Transformers.js).`);
  }
  instance ??= createLocalEmbedder();
  return instance;
}
