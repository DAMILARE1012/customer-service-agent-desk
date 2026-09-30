import client from 'prom-client';

// Prometheus metrics, scraped from GET /metrics. Labels only ever take a handful of values
// (model, stage, reason…) — never conversation or customer IDs, which would explode cardinality.
// Per-conversation detail lives in Langfuse traces instead.

export const registry = new client.Registry();
registry.setDefaultLabels({ service: 'support-api' });
client.collectDefaultMetrics({ register: registry }); // CPU, memory, event-loop lag, GC

const metric = (Type, options) => new Type({ registers: [registry], ...options });

// ── HTTP ────────────────────────────────────────────────────────────────────
export const httpRequests = metric(client.Counter, {
  name: 'http_requests_total',
  help: 'HTTP requests by route and status',
  labelNames: ['method', 'route', 'status'],
});
export const httpDuration = metric(client.Histogram, {
  name: 'http_request_duration_seconds',
  help: 'HTTP request latency',
  labelNames: ['method', 'route'],
  buckets: [0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16],
});

// ── RAG pipeline ────────────────────────────────────────────────────────────
export const stageDuration = metric(client.Histogram, {
  name: 'rag_stage_duration_seconds',
  help: 'Latency of each pipeline stage',
  labelNames: ['stage'], // retrieve | generate | copilot | judge
  buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16],
});
export const retrievalConfidence = metric(client.Histogram, {
  name: 'rag_retrieval_confidence',
  help: 'Cosine similarity of the top retrieved chunk per bot turn',
  buckets: [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
});
export const botTurns = metric(client.Counter, {
  name: 'rag_bot_turns_total',
  help: 'Bot turns by outcome',
  labelNames: ['outcome'], // answered | clarified | handed_off | small_talk
});

// ── LLM (Groq) ──────────────────────────────────────────────────────────────
export const llmRequests = metric(client.Counter, {
  name: 'llm_requests_total',
  help: 'LLM calls by model, purpose and result',
  labelNames: ['model', 'purpose', 'status'], // status: ok | rate_limited | error | timeout
});
export const llmDuration = metric(client.Histogram, {
  name: 'llm_request_duration_seconds',
  help: 'LLM call latency including retries',
  labelNames: ['model', 'purpose'],
  buckets: [0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32],
});
export const llmTokens = metric(client.Counter, {
  name: 'llm_tokens_total',
  help: 'Tokens used',
  labelNames: ['model', 'purpose', 'type'], // type: prompt | completion
});
export const llmCost = metric(client.Counter, {
  name: 'llm_cost_usd_total',
  help: 'Estimated LLM spend (from LLM_PRICES_PER_MILLION)',
  labelNames: ['model', 'purpose'],
});

// ── Handoff & desk ──────────────────────────────────────────────────────────
export const handoffs = metric(client.Counter, {
  name: 'handoffs_total',
  help: 'Handoffs to a human by primary reason and priority',
  labelNames: ['reason', 'priority'],
});
export const handoffWait = metric(client.Histogram, {
  name: 'handoff_wait_seconds',
  help: 'Time from handoff to an agent accepting it',
  labelNames: ['priority'],
  buckets: [15, 30, 60, 120, 300, 600, 1200, 1800, 3600],
});
export const copilotDrafts = metric(client.Counter, {
  name: 'copilot_drafts_total',
  help: 'What agents did with the copilot draft when they replied',
  labelNames: ['action'], // used | edited | ignored
});
export const onlineEvalScore = metric(client.Histogram, {
  name: 'online_eval_score',
  help: 'LLM-judge scores on sampled live answers (0–1)',
  labelNames: ['metric'], // faithfulness | answer_relevance
  buckets: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1],
});

/**
 * Gauges computed at scrape time from live state (conversation store, knowledge index).
 * @param {() => { byStatus: Record<string, number>, oldestHandoffWaitSeconds: number, slaBreaches: number }} readDesk
 * @param {() => { chunks: number, builtAt: number | null, checkedAt: Record<string, number> }} readIndex
 */
export function registerStateGauges(readDesk, readIndex) {
  metric(client.Gauge, {
    name: 'conversations',
    help: 'Open conversations by status',
    labelNames: ['status'],
    collect() {
      for (const [status, count] of Object.entries(readDesk().byStatus)) this.set({ status }, count);
    },
  });
  metric(client.Gauge, {
    name: 'handoff_queue_oldest_wait_seconds',
    help: 'How long the longest-waiting handoff has been waiting',
    collect() {
      this.set(readDesk().oldestHandoffWaitSeconds);
    },
  });
  metric(client.Gauge, {
    name: 'handoff_sla_breaches',
    help: 'Handoffs currently waiting longer than the breach SLA',
    collect() {
      this.set(readDesk().slaBreaches);
    },
  });
  metric(client.Gauge, {
    name: 'knowledge_index_chunks',
    help: 'Searchable chunks in the knowledge index',
    collect() {
      this.set(readIndex().chunks);
    },
  });
  metric(client.Gauge, {
    name: 'knowledge_source_last_checked_timestamp_seconds',
    help: 'When each knowledge source was last checked for changes',
    labelNames: ['source'],
    collect() {
      for (const [source, at] of Object.entries(readIndex().checkedAt)) this.set({ source }, at / 1000);
    },
  });
}

/** Time an async stage into a histogram. */
export async function timed(histogram, labels, fn) {
  const end = histogram.startTimer(labels);
  try {
    return await fn();
  } finally {
    end();
  }
}
