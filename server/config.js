import path from 'node:path';

// Server-side configuration, read from the same `.env` as the frontend (see `.env.example`).
// Unlike the browser config, invalid values fail fast: a bad threshold should stop a run, not warn.
try {
  process.loadEnvFile(path.resolve(import.meta.dirname, '..', '.env'));
} catch {
  /* no .env — defaults apply */
}

const env = process.env;

function number(name, fallback, { min = -Infinity, max = Infinity, integer = false } = {}) {
  const raw = env[name];
  if (raw === undefined || raw.trim() === '') return fallback;
  const value = Number(raw);
  if (Number.isNaN(value) || value < min || value > max || (integer && !Number.isInteger(value))) {
    throw new Error(`[config] ${name}="${raw}" is invalid (expected ${integer ? 'an integer ' : ''}between ${min} and ${max}).`);
  }
  return value;
}

const string = (name, fallback = '') => env[name]?.trim() || fallback;
function json(name, fallback) {
  const raw = string(name);
  if (!raw) return fallback;
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`[config] ${name} is not valid JSON: ${raw}`);
  }
}

const list = (name, fallback) => string(name, fallback).split(',').map((s) => s.trim()).filter(Boolean);

const root = path.resolve(import.meta.dirname, '..');
const dataDir = path.resolve(root, string('DATA_DIR', 'data'));

export const config = {
  paths: {
    root,
    content: path.resolve(root, string('CONTENT_DIR', 'content')),
    raw: path.join(dataDir, 'raw'),
    index: path.join(dataDir, 'index'),
    models: path.join(dataDir, 'models'),
    eval: path.join(dataDir, 'eval'),
  },

  embedding: {
    provider: string('EMBEDDING_PROVIDER', 'local'),
    model: string('EMBEDDING_MODEL', 'Xenova/bge-small-en-v1.5'),
    dtype: string('EMBEDDING_DTYPE', 'q8'),
    pooling: string('EMBEDDING_POOLING', 'cls'), // BGE models use CLS pooling; MiniLM-style models use "mean"
    queryPrefix: string('EMBEDDING_QUERY_PREFIX', 'Represent this sentence for searching relevant passages:'),
    batchSize: number('EMBEDDING_BATCH_SIZE', 32, { min: 1, max: 256, integer: true }),
  },

  chunking: {
    minTokens: number('CHUNK_MIN_TOKENS', 50, { min: 0, integer: true }),
    targetTokens: number('CHUNK_TARGET_TOKENS', 300, { min: 50, integer: true }),
    maxTokens: number('CHUNK_MAX_TOKENS', 450, { min: 50, max: 500, integer: true }), // model reads 512 incl. title
  },

  ingest: {
    sources: list('INGEST_SOURCES', 'local,wixqa,abcd'),
    // Minutes between upstream checks. 0 = check on every run.
    refreshMinutes: {
      local: number('SOURCE_LOCAL_REFRESH_MINUTES', 0, { min: 0 }),
      wixqa: number('SOURCE_WIXQA_REFRESH_MINUTES', 10080, { min: 0 }),
      abcd: number('SOURCE_ABCD_REFRESH_MINUTES', 10080, { min: 0 }),
    },
  },

  retrieval: {
    topK: number('RETRIEVAL_TOP_K', 5, { min: 1, integer: true }),
    candidates: number('RETRIEVAL_CANDIDATES', 50, { min: 1, integer: true }),
    rrfK: number('RETRIEVAL_RRF_K', 60, { min: 1 }),
  },

  eval: {
    answerPrecision: number('EVAL_ANSWER_PRECISION', 0.8, { min: 0, max: 1 }),
    copilotPrecision: number('EVAL_COPILOT_PRECISION', 0.6, { min: 0, max: 1 }),
    noMatchMaxMissRate: number('EVAL_NO_MATCH_MAX_MISS_RATE', 0.05, { min: 0, max: 1 }),
    // End-to-end experiment (npm run eval:rag)
    ragLimit: number('EVAL_RAG_LIMIT', 50, { min: 1, integer: true }),
    ragConcurrency: number('EVAL_RAG_CONCURRENCY', 2, { min: 1, max: 16, integer: true }),
    ragDataset: string('EVAL_RAG_DATASET', 'support-bot-eval'),
  },

  server: {
    port: number('SERVER_PORT', 8787, { min: 1, max: 65535, integer: true }),
    corsOrigin: string('CORS_ORIGIN', '*'),
  },

  // Same values the desk UI uses for its wait-time colouring, so metrics and screen agree.
  sla: {
    warnAfterMs: number('VITE_HANDOFF_SLA_WARN_SECONDS', 120, { min: 1 }) * 1000,
    breachAfterMs: number('VITE_HANDOFF_SLA_BREACH_SECONDS', 300, { min: 1 }) * 1000,
  },

  llm: {
    apiKey: string('GROQ_API_KEY'),
    baseUrl: string('GROQ_BASE_URL', 'https://api.groq.com/openai/v1').replace(/\/$/, ''),
    model: string('GROQ_MODEL', 'llama-3.1-8b-instant'),
    temperature: number('LLM_TEMPERATURE', 0.2, { min: 0, max: 2 }),
    maxTokens: number('LLM_MAX_TOKENS', 512, { min: 16, integer: true }),
    // Only for reasoning models (e.g. openai/gpt-oss-*): low | medium | high. Their reasoning tokens
    // count toward LLM_MAX_TOKENS, so raise that too (1024+). Leave empty for Llama-style models.
    reasoningEffort: string('LLM_REASONING_EFFORT'),
    timeoutMs: number('LLM_TIMEOUT_MS', 15000, { min: 1000, integer: true }),
    maxRetries: number('LLM_MAX_RETRIES', 2, { min: 0, max: 5, integer: true }),
    // USD per million tokens, [input, output], for cost tracking. Check current prices in the Groq console.
    prices: json('LLM_PRICES_PER_MILLION', {}),
  },

  judge: {
    model: string('JUDGE_MODEL', 'openai/gpt-oss-120b'),
    reasoningEffort: string('JUDGE_REASONING_EFFORT', 'medium'),
    maxTokens: number('JUDGE_MAX_TOKENS', 4096, { min: 256, integer: true }),
    // Judge calls are large (~3k tokens). On Groq's on-demand tier gpt-oss-120b allows 8,000 tokens
    // per minute, so judgments run one at a time and wait out rate limits instead of failing.
    concurrency: number('JUDGE_CONCURRENCY', 1, { min: 1, max: 8, integer: true }),
    maxRetries: number('JUDGE_MAX_RETRIES', 6, { min: 0, max: 20, integer: true }),
  },

  // How the real backend decides to step aside. Calibrated with `npm run eval` for this retriever —
  // these are cosine similarities, unlike the demo's keyword-score VITE_HANDOFF_* values.
  policy: {
    noMatchThreshold: number('RAG_NO_MATCH_THRESHOLD', 0.7, { min: 0, max: 1 }),
    contextChunks: number('RAG_CONTEXT_CHUNKS', 5, { min: 1, max: 20, integer: true }),
    maxFailedAttempts: number('RAG_MAX_FAILED_ATTEMPTS', 2, { min: 1, integer: true }),
    sentimentThreshold: number('RAG_SENTIMENT_THRESHOLD', -0.5, { min: -1, max: 1 }),
    procedureThreshold: number('RAG_PROCEDURE_THRESHOLD', 0.72, { min: 0, max: 1 }),
  },

  observability: {
    langfuseEnabled: Boolean(string('LANGFUSE_PUBLIC_KEY') && string('LANGFUSE_SECRET_KEY')),
    langfuseBaseUrl: string('LANGFUSE_BASE_URL', 'http://localhost:3000'),
    environment: string('LANGFUSE_TRACING_ENVIRONMENT', 'development'),
    // Share of live bot answers scored by the LLM judge (faithfulness, relevance). 0 disables.
    onlineEvalSampleRate: number('ONLINE_EVAL_SAMPLE_RATE', 0.2, { min: 0, max: 1 }),
  },
};

if (config.chunking.targetTokens > config.chunking.maxTokens) {
  throw new Error('[config] CHUNK_TARGET_TOKENS must not exceed CHUNK_MAX_TOKENS.');
}
