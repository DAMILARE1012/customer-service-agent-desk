import { config } from '../config.js';
import { chatJson } from '../llm/groq.js';
import { stageDuration, timed } from '../observability/metrics.js';

// LLM-as-judge, run on a stronger model from a different family than the answering model
// (JUDGE_MODEL, default gpt-oss-120b) to avoid a model grading its own work.
//
// Scores are decomposed rather than asked for directly, which is more reliable:
//   faithfulness   = supported claims / claims in the answer          (no reference needed)
//   context_recall = reference facts present in the context / facts   (needs a reference answer)
//   answer_relevance, answer_correctness = 1–5 ratings scaled to 0–1

const CLAIMS = {
  type: 'array',
  items: {
    type: 'object',
    properties: { claim: { type: 'string' }, supported: { type: 'boolean' } },
    required: ['claim', 'supported'],
    additionalProperties: false,
  },
};
const FACTS = {
  type: 'array',
  items: {
    type: 'object',
    properties: { fact: { type: 'string' }, in_context: { type: 'boolean' } },
    required: ['fact', 'in_context'],
    additionalProperties: false,
  },
};

const MODES = {
  // Live traffic: no reference answer exists.
  answer: {
    properties: { claims: CLAIMS, answer_relevance: { type: 'integer' }, reasoning: { type: 'string' } },
    instructions: `1. "claims": split the ANSWER into short atomic factual claims (ignore greetings and pleasantries). For each, "supported" is true only if the CONTEXT explicitly states or directly implies it.
2. "answer_relevance" (1–5): how directly and completely the ANSWER addresses the QUESTION, regardless of correctness. 5 = fully on point; 1 = off-topic.`,
  },
  // Offline evaluation: a reference answer is available.
  reference: {
    properties: {
      claims: CLAIMS,
      answer_relevance: { type: 'integer' },
      answer_correctness: { type: 'integer' },
      reference_facts: FACTS,
      reasoning: { type: 'string' },
    },
    instructions: `1. "claims": split the ANSWER into short atomic factual claims (ignore greetings and pleasantries). For each, "supported" is true only if the CONTEXT explicitly states or directly implies it.
2. "answer_relevance" (1–5): how directly and completely the ANSWER addresses the QUESTION, regardless of correctness.
3. "answer_correctness" (1–5): agreement between the ANSWER and the REFERENCE on the key facts and steps. 5 = same key facts, nothing contradicted; 3 = partly right or missing important steps; 1 = wrong, contradicts the reference, or misses the point.
4. "reference_facts": split the REFERENCE into its key facts. For each, "in_context" is true if the CONTEXT contains that information.`,
  },
  // The bot didn't answer: only judge whether the retrieved context could have supported an answer.
  context: {
    properties: { reference_facts: FACTS, reasoning: { type: 'string' } },
    instructions: `1. "reference_facts": split the REFERENCE into its key facts. For each, "in_context" is true if the CONTEXT contains that information.`,
  },
};

// Judgments share one per-minute token budget, so they queue (JUDGE_CONCURRENCY at a time)
// no matter how many questions run in parallel.
let active = 0;
const waiting = [];
async function withJudgeSlot(fn) {
  if (active >= config.judge.concurrency) await new Promise((resolve) => waiting.push(resolve));
  active += 1;
  try {
    return await fn();
  } finally {
    active -= 1;
    waiting.shift()?.();
  }
}

const scale5 = (value) => (Number.isFinite(value) ? (Math.min(5, Math.max(1, value)) - 1) / 4 : null);
const share = (items, key) => (items?.length ? items.filter((item) => item[key]).length / items.length : null);

/**
 * @param {{ question: string, contexts: string[], answer?: string, reference?: string }} params
 * @returns {Promise<{ faithfulness: number|null, unsupportedClaims: string[], answerRelevance: number|null,
 *                     answerCorrectness: number|null, contextRecall: number|null, reasoning: string } | null>}
 */
export async function judge({ question, contexts, answer = '', reference = '' }) {
  const mode = answer ? (reference ? 'reference' : 'answer') : reference ? 'context' : null;
  if (!mode) return null;
  const { properties, instructions } = MODES[mode];

  const prompt = [
    `QUESTION:\n${question}`,
    `CONTEXT (what the assistant retrieved):\n${contexts.map((c, i) => `[${i + 1}] ${c}`).join('\n\n') || '(nothing retrieved)'}`,
    answer && `ANSWER (from the assistant):\n${answer}`,
    reference && `REFERENCE (correct answer written by a support expert):\n${reference}`,
  ]
    .filter(Boolean)
    .join('\n\n');

  const { json } = await withJudgeSlot(() => timed(stageDuration, { stage: 'judge' }, () =>
    chatJson({
      purpose: 'judge',
      model: config.judge.model,
      temperature: 0,
      maxTokens: config.judge.maxTokens,
      reasoningEffort: config.judge.reasoningEffort,
      maxRetries: config.judge.maxRetries,
      responseFormat: {
        type: 'json_schema',
        json_schema: {
          name: `judge_${mode}`,
          strict: true,
          schema: { type: 'object', properties, required: Object.keys(properties), additionalProperties: false },
        },
      },
      messages: [
        {
          role: 'system',
          content: `You are a strict, impartial evaluator of a customer-support assistant. Judge only against the material given; do not use outside knowledge.\n\n${instructions}\n\nKeep "reasoning" to one or two sentences.`,
        },
        { role: 'user', content: prompt },
      ],
    }),
  ));

  return {
    faithfulness: share(json.claims, 'supported'),
    unsupportedClaims: (json.claims ?? []).filter((c) => !c.supported).map((c) => c.claim),
    answerRelevance: scale5(json.answer_relevance),
    answerCorrectness: scale5(json.answer_correctness),
    contextRecall: share(json.reference_facts, 'in_context'),
    reasoning: json.reasoning ?? '',
  };
}
