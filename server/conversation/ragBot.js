import { getActiveTraceId, setActiveTraceIO, startActiveObservation } from '@langfuse/tracing';
import { addBotMessage, recordAttempt, requestHandoff } from '../../src/api/mock/engine/conversationEngine.js';
import { detectSmallTalk } from '../../src/api/mock/engine/handoffPolicy.js';
import { truncate } from '../../src/api/mock/engine/text.js';
import { BOT_REPLY_KIND, SENDER } from '../../src/constants/conversation.js';
import { HANDOFF_REASON } from '../../src/constants/handoff.js';
import { config } from '../config.js';
import { botTurns, handoffs } from '../observability/metrics.js';
import { maybeScoreAnswer } from '../observability/onlineEval.js';
import { answerQuestion, findProcedure, toSourceRef } from '../rag/answerer.js';
import { answerSignals, conversationSignals, decide } from './policy.js';

// The real bot: the same lifecycle as the demo, with retrieval + Groq in place of the mock engine.

const historyOf = (conversation, excludeId) =>
  conversation.messages.filter((m) => m.id !== excludeId && m.sender !== SENDER.SYSTEM).map((m) => ({ sender: m.sender, text: m.text }));

/** The shape the shared attempt log expects: confidence + the articles involved. */
const attemptRetrieval = (result) => ({
  confidence: result.retrieval.confidence,
  hits: (result.citations.length ? result.citations : result.retrieval.results).map((r) => ({ id: r.docId, title: r.title })),
});

function updateIntent(insights, retrieval) {
  const [top] = retrieval.results;
  if (top && top.similarity >= config.policy.noMatchThreshold && top.similarity >= (insights.intent?.confidence ?? 0)) {
    insights.intent = { label: top.category, confidence: top.similarity };
  }
}

/** Add what this turn's retrieval found, and the matching agent procedure, to the handoff brief. */
async function enrichHandoff(conversation, result, question) {
  const { handoff } = conversation;
  const fresh = result.retrieval.results.filter((r) => r.similarity >= config.policy.noMatchThreshold).map(toSourceRef);
  const best = new Map();
  for (const source of [...handoff.sources, ...fresh]) {
    if (!best.has(source.id) || source.score > best.get(source.id).score) best.set(source.id, source);
  }
  handoff.sources = [...best.values()].sort((a, b) => b.score - a.score).slice(0, 5);

  const procedure = await findProcedure(question);
  if (procedure) {
    handoff.procedure = { title: procedure.title, url: procedure.url, similarity: procedure.similarity };
    handoff.suggestedNextSteps.push(`Follow the internal “${procedure.title}” procedure.`);
  }
}

function clarifyingQuestion(result) {
  const [top] = result.retrieval.results;
  const hint = top && top.similarity >= config.policy.noMatchThreshold ? ` Is this about ${top.title.replace(/[.?!]$/, '').toLowerCase()}?` : '';
  return `I want to make sure I get this right.${hint} Could you tell me a bit more — what you're trying to do and where you're seeing the problem?`;
}

async function runTurn(conversation, message, sentiment, now) {
  const { insights } = conversation;

  const smallTalk = detectSmallTalk(message.text);
  if (smallTalk && sentiment > config.policy.sentimentThreshold) {
    const text = smallTalk === 'greeting' ? 'Hi! How can I help today?' : 'You’re welcome! Is there anything else I can help with?';
    addBotMessage(conversation, text, now, { kind: BOT_REPLY_KIND.SMALL_TALK, confidence: null, sources: [] });
    return { kind: 'small_talk', reply: text };
  }

  // Conversation-level signals first: if a handoff is already certain, skip the LLM entirely.
  const early = conversationSignals({ text: message.text, sentiment });
  const result = await answerQuestion({ question: message.text, history: historyOf(conversation, message.id), generate: early.length === 0 });
  insights.lastConfidence = result.retrieval.confidence;
  updateIntent(insights, result.retrieval);

  const decision = decide([...early, ...(early.length ? [] : answerSignals({ result, text: message.text, failedAttempts: insights.failedAttempts }))]);

  if (decision.shouldHandoff) {
    const bareRequest = decision.primary.reason === HANDOFF_REASON.CUSTOMER_REQUEST && result.retrieval.confidence < config.policy.noMatchThreshold;
    if (!bareRequest) recordAttempt(insights, message, null, 'handed_off', attemptRetrieval(result), now);
    requestHandoff(conversation, decision, message, now);
    await enrichHandoff(conversation, result, message.text);
    handoffs.inc({ reason: decision.primary.reason, priority: conversation.handoff.priority });
    return { kind: 'handed_off', reason: decision.primary.reason, signals: decision.signals.map((s) => s.reason), status: result.status };
  }

  if (result.status === 'answered') {
    const traceId = getActiveTraceId();
    const reply = addBotMessage(conversation, result.answer, now, {
      kind: BOT_REPLY_KIND.ANSWER,
      confidence: result.retrieval.confidence,
      sources: result.citations.map(toSourceRef),
      traceId,
    });
    recordAttempt(insights, message, reply, 'answered', attemptRetrieval(result), now);
    insights.failedAttempts = 0;
    maybeScoreAnswer({ traceId, question: message.text, contexts: result.retrieval.results.map((r) => r.text), answer: result.answer });
    return { kind: 'answered', reply: result.answer, citations: result.citations.map((c) => c.id) };
  }

  const text = clarifyingQuestion(result);
  const reply = addBotMessage(conversation, text, now, {
    kind: BOT_REPLY_KIND.CLARIFY,
    confidence: result.retrieval.confidence,
    sources: result.retrieval.results.slice(0, 3).map(toSourceRef),
  });
  recordAttempt(insights, message, reply, 'clarified', attemptRetrieval(result), now);
  insights.failedAttempts += 1;
  return { kind: 'clarified', reply: text, status: result.status };
}

/** One bot turn, traced as a Langfuse agent observation and counted in Prometheus. */
export function botTurn(conversation, message, sentiment, now) {
  return startActiveObservation(
    'bot-turn',
    async (span) => {
      span.update({ input: message.text });
      const outcome = await runTurn(conversation, message, sentiment, now);
      setActiveTraceIO({ input: message.text, output: outcome.reply ?? `[handed off: ${outcome.reason}]` });
      span.update({ output: outcome, metadata: { conversationStatus: conversation.status, sentiment } });
      botTurns.inc({ outcome: outcome.kind });
      return outcome;
    },
    { asType: 'agent' },
  );
}

/** A grounded draft for the agent, or null when the knowledge base can't support one. */
export function draftCopilot(conversation, question) {
  if (!question) return Promise.resolve(null);
  return startActiveObservation(
    'copilot-draft',
    async (span) => {
      span.update({ input: question });
      const result = await answerQuestion({ question, history: historyOf(conversation), purpose: 'copilot' });
      span.update({ output: { status: result.status, answer: result.answer } });
      if (result.status !== 'answered') return null;
      return {
        text: result.answer,
        basedOn: truncate(question, 120),
        confidence: result.retrieval.confidence,
        sources: result.citations.map(toSourceRef),
      };
    },
    { asType: 'agent' },
  );
}
