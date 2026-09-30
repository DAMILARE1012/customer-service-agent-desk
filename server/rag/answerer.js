import fs from 'node:fs/promises';
import path from 'node:path';
import { startActiveObservation } from '@langfuse/tracing';
import { config } from '../config.js';
import { chatJson } from '../llm/groq.js';
import { retrievalConfidence, stageDuration, timed } from '../observability/metrics.js';
import { createRetriever } from './retriever.js';

const RELOAD_CHECK_MS = 60_000;
let retrieverPromise = null;
let lastReloadCheck = Date.now();

async function reloadIfRebuilt() {
  try {
    const { builtAt } = JSON.parse(await fs.readFile(path.join(config.paths.index, 'manifest.json'), 'utf8'));
    const active = (await retrieverPromise).manifest.builtAt;
    if (builtAt === active) return;
    const next = createRetriever();
    await next; // keep serving from the old index until the new one is ready
    retrieverPromise = next;
    console.log(`[retriever] reloaded knowledge index built at ${builtAt}`);
  } catch (error) {
    console.warn(`[retriever] reload check failed: ${error.message}`);
  }
}

/**
 * One shared retriever per process (loading the index and model takes a few seconds).
 * Picks up a rebuilt index (after `npm run ingest`) within a minute, without a restart.
 */
export function getRetriever() {
  retrieverPromise ??= createRetriever();
  if (Date.now() - lastReloadCheck > RELOAD_CHECK_MS) {
    lastReloadCheck = Date.now();
    void reloadIfRebuilt();
  }
  return retrieverPromise;
}

const SYSTEM_PROMPT = `You are a customer-support assistant. Reply to the customer's latest message using ONLY the numbered knowledge-base sources provided.

Rules:
- If the sources do not contain what is needed to answer, set "answerable" to false and "answer" to "". Never guess and never use outside knowledge.
- Every statement in the answer must be supported by the sources. Put the numbers of the sources you used in "citations".
- Be concise (under 120 words), friendly and practical. Give step-by-step instructions when the source has them.
- Never invent order details, prices, deadlines, policies or links.
- Do not mention "sources", "documents" or the knowledge base in the answer.

Respond with a JSON object only, in this shape: {"answerable": true, "answer": "…", "citations": [1]}`;

const SPEAKER = { customer: 'Customer', bot: 'Assistant', agent: 'Agent' };

function formatSources(results) {
  return results
    .map((r, i) => {
      const section = r.headingPath.length ? ` › ${r.headingPath.join(' › ')}` : '';
      return `[${i + 1}] ${r.title}${section}\n${r.text}`;
    })
    .join('\n\n');
}

function formatHistory(history) {
  return history
    .filter((m) => SPEAKER[m.sender])
    .slice(-6)
    .map((m) => `${SPEAKER[m.sender]}: ${m.text}`)
    .join('\n');
}

/** Short follow-ups ("what about express?") are searched together with the previous question. */
function retrievalQuery(question, history) {
  const previous = history.findLast((m) => m.sender === 'customer' && m.text !== question)?.text;
  return previous && question.split(/\s+/).length < 6 ? `${previous}\n${question}` : question;
}

export const toSourceRef = (result) => ({
  id: result.id,
  docId: result.docId,
  title: result.title,
  url: result.url,
  category: result.category,
  snippet: result.text.replace(/\s+/g, ' ').slice(0, 180),
  score: result.similarity,
});

export function retrieve(query, { audience = 'customer', topK = config.policy.contextChunks } = {}) {
  return startActiveObservation(
    'retrieve',
    async (span) => {
      span.update({ input: { query, audience, topK } });
      const retriever = await getRetriever();
      const { confidence, results } = await timed(stageDuration, { stage: 'retrieve' }, () => retriever.search(query, { audience, topK }));
      span.update({
        output: results.map((r) => ({ id: r.id, title: r.title, section: r.headingPath.join(' › '), similarity: r.similarity })),
        metadata: { confidence },
      });
      return { confidence, results };
    },
    { asType: 'retriever' },
  );
}

/**
 * Retrieve → (gate on confidence) → generate a cited answer.
 *
 * status:
 *   answered      grounded answer with at least one valid citation
 *   unanswerable  the model found the sources insufficient (or answered without citing)
 *   no_match      retrieval confidence below RAG_NO_MATCH_THRESHOLD — the LLM isn't called
 *   skipped       generate=false (e.g. a handoff is already certain); retrieval still runs for the brief
 *   error         the LLM failed or timed out
 *
 * @param {{ question: string, history?: { sender: string, text: string }[], generate?: boolean, purpose?: 'answer' | 'copilot' | 'eval' }} params
 */
export async function answerQuestion({ question, history = [], generate = true, purpose = 'answer' }) {
  const retrieval = await retrieve(retrievalQuery(question, history));
  if (purpose === 'answer') retrievalConfidence.observe(retrieval.confidence);

  if (!generate) return { status: 'skipped', retrieval, citations: [], answer: '' };
  if (retrieval.confidence < config.policy.noMatchThreshold) return { status: 'no_match', retrieval, citations: [], answer: '' };

  const conversation = formatHistory(history);
  const messages = [
    { role: 'system', content: SYSTEM_PROMPT },
    {
      role: 'user',
      content: `Sources:\n${formatSources(retrieval.results)}\n\n${conversation ? `Conversation so far:\n${conversation}\n\n` : ''}Latest customer message:\n${question}`,
    },
  ];

  try {
    const stage = purpose === 'copilot' ? 'copilot' : 'generate';
    const { json } = await timed(stageDuration, { stage }, () =>
      chatJson({ purpose, messages, responseFormat: { type: 'json_object' }, reasoningEffort: config.llm.reasoningEffort || undefined }),
    );

    const cited = [...new Set((Array.isArray(json.citations) ? json.citations : []).map(Number))]
      .filter((n) => Number.isInteger(n) && n >= 1 && n <= retrieval.results.length)
      .map((n) => retrieval.results[n - 1]);
    const answer = typeof json.answer === 'string' ? json.answer.trim() : '';
    // No citation, no answer: an uncited reply can't be checked, so it's treated as "can't answer".
    const grounded = json.answerable === true && answer.length > 0 && cited.length > 0;

    return {
      status: grounded ? 'answered' : 'unanswerable',
      answer: grounded ? answer : '',
      citations: grounded ? cited : [],
      retrieval,
      uncited: json.answerable === true && answer.length > 0 && cited.length === 0,
    };
  } catch (error) {
    return { status: 'error', retrieval, citations: [], answer: '', error: error.message };
  }
}

/** The best-matching agent procedure (ABCD guidelines), if one is relevant enough to suggest. */
export async function findProcedure(query) {
  const { results } = await retrieve(query, { audience: 'agent', topK: 1 });
  const [top] = results;
  return top && top.similarity >= config.policy.procedureThreshold ? top : null;
}
