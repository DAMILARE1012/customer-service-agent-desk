import { BOT_REPLY_KIND, CONVERSATION_STATUS, SENDER, SYSTEM_EVENT } from '../../../constants/conversation.js';
import { HANDOFF_REASON, HANDOFF_REASON_META, HANDOFF_STATUS } from '../../../constants/handoff.js';
import { extractEntities, mergeEntities } from './entities.js';
import { buildHandoffPacket } from './handoffPacket.js';
import { HANDOFF_POLICY, detectSmallTalk, evaluateHandoff } from './handoffPolicy.js';
import { retrieve, toSourceRef } from './retrieval.js';
import { scoreSentiment } from './sentiment.js';
import { truncate } from './text.js';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

let sequence = 1000;
const nextId = (prefix) => `${prefix}_${++sequence}`;

const { BOT_ACTIVE, HANDOFF_PENDING, AGENT_ACTIVE, RESOLVED } = CONVERSATION_STATUS;

// ─── helpers (exported for the real backend in server/conversation) ─────────────

export function addMessage(conversation, message) {
  const full = { id: nextId('msg'), meta: null, event: null, author: null, ...message };
  conversation.messages.push(full);
  conversation.updatedAt = full.createdAt;
  return full;
}

export const addSystemEvent = (conversation, type, text, now, extra = {}) =>
  addMessage(conversation, { sender: SENDER.SYSTEM, text, createdAt: now, event: { type, ...extra } });

export const addBotMessage = (conversation, text, now, meta) =>
  addMessage(conversation, { sender: SENDER.BOT, text, createdAt: now, meta });

function assertStatus(conversation, allowed, action) {
  if (!allowed.includes(conversation.status)) {
    throw new ApiError(409, `Cannot ${action} while conversation is ${conversation.status}.`);
  }
}

const HANDOFF_NOTICE = {
  [HANDOFF_REASON.CUSTOMER_REQUEST]:
    'Of course — I’m connecting you with a member of our support team now. I’ve passed along everything we’ve discussed, so you won’t need to repeat yourself.',
  [HANDOFF_REASON.SENSITIVE_TOPIC]:
    'This is something a member of our team should handle personally. I’m connecting you now and have shared the details you’ve given me.',
  [HANDOFF_REASON.NEGATIVE_SENTIMENT]:
    'I’m sorry this has been frustrating. I’m bringing in someone from our team who can sort this out — they’ll see our full conversation.',
  [HANDOFF_REASON.REPEATED_FAILURE]:
    'I don’t want to keep guessing. I’m connecting you with a teammate who can help, and I’ve shared what we’ve covered so far.',
  [HANDOFF_REASON.LOW_CONFIDENCE]:
    'That’s outside what I can answer reliably, so I’m connecting you with a teammate. They’ll have our conversation, so no need to start over.',
  [HANDOFF_REASON.ASSISTANT_UNAVAILABLE]:
    'I’m having trouble answering right now, so I’m connecting you with a member of our team. They’ll see everything you’ve told me.',
};

// ─── lifecycle ────────────────────────────────────────────────────────────────

export function createConversation(customer, now) {
  return {
    id: nextId('conv'),
    customer,
    status: BOT_ACTIVE,
    assignee: null,
    subject: null,
    createdAt: now,
    updatedAt: now,
    messages: [],
    insights: {
      intent: null,
      lastConfidence: null,
      sentiment: { current: 0, trend: [] },
      entities: [],
      attempts: [],
      failedAttempts: 0,
    },
    handoff: null,
    handoffHistory: [],
    copilot: null,
  };
}

export function trackSignals(conversation, message) {
  const { insights } = conversation;
  const sentiment = scoreSentiment(message.text);
  // Smooth so one sharp message registers but a single "thanks" doesn't erase frustration.
  const previous = insights.sentiment.trend.at(-1);
  const current = previous === undefined ? sentiment : Math.round((sentiment * 0.7 + previous * 0.3) * 100) / 100;
  insights.sentiment = { current, trend: [...insights.sentiment.trend, current] };
  insights.entities = mergeEntities(insights.entities, extractEntities(message.text, message.id));
  return current;
}

export function receiveCustomerMessage(conversation, text, now) {
  if (conversation.status === RESOLVED) {
    conversation.status = BOT_ACTIVE;
    conversation.assignee = null;
    addSystemEvent(conversation, SYSTEM_EVENT.REOPENED, 'Customer replied — conversation reopened', now);
  }

  const message = addMessage(conversation, { sender: SENDER.CUSTOMER, text, createdAt: now });
  conversation.subject ??= truncate(text, 70);
  const sentiment = trackSignals(conversation, message);

  if (conversation.status === BOT_ACTIVE) runBotTurn(conversation, message, sentiment, now);
  else if (conversation.status === AGENT_ACTIVE) conversation.copilot = draftCopilotReply(text);
  // HANDOFF_PENDING: the bot has stepped aside; it just keeps listening so the packet stays useful.

  return conversation;
}

function runBotTurn(conversation, message, sentiment, now) {
  const { insights } = conversation;

  const smallTalk = detectSmallTalk(message.text);
  if (smallTalk && insights.sentiment.current > HANDOFF_POLICY.sentimentThreshold) {
    const reply = smallTalk === 'greeting' ? 'Hi! How can I help today?' : 'You’re welcome! Is there anything else I can help with?';
    addBotMessage(conversation, reply, now, { kind: BOT_REPLY_KIND.SMALL_TALK, confidence: null, sources: [] });
    return;
  }

  const retrieval = retrieve(message.text);
  const [top] = retrieval.hits;
  insights.lastConfidence = retrieval.confidence;
  // Keep the strongest intent seen so far; a weak later match shouldn't overwrite a confident one.
  if (top && top.score >= HANDOFF_POLICY.noMatchThreshold && top.score >= (insights.intent?.confidence ?? 0)) {
    insights.intent = { label: top.category, confidence: top.score };
  }

  const decision = evaluateHandoff({
    text: message.text,
    retrieval,
    sentiment,
    failedAttempts: insights.failedAttempts,
  });

  if (decision.shouldHandoff) {
    const isBareRequest =
      decision.primary.reason === HANDOFF_REASON.CUSTOMER_REQUEST && retrieval.confidence < HANDOFF_POLICY.noMatchThreshold;
    if (!isBareRequest) recordAttempt(insights, message, null, 'handed_off', retrieval, now);
    requestHandoff(conversation, decision, message, now);
    return;
  }

  const sources = retrieval.hits.map(toSourceRef);
  if (retrieval.confidence >= HANDOFF_POLICY.answerThreshold) {
    const reply = addBotMessage(conversation, top.answer, now, { kind: BOT_REPLY_KIND.ANSWER, confidence: retrieval.confidence, sources });
    recordAttempt(insights, message, reply, 'answered', retrieval, now);
    insights.failedAttempts = 0;
  } else {
    const hint = top ? ` Is this about ${top.title.toLowerCase()}?` : '';
    const reply = addBotMessage(
      conversation,
      `I want to make sure I get this right.${hint} Could you share a bit more detail — for example an order number or what you’ve already tried?`,
      now,
      { kind: BOT_REPLY_KIND.CLARIFY, confidence: retrieval.confidence, sources },
    );
    recordAttempt(insights, message, reply, 'clarified', retrieval, now);
    insights.failedAttempts += 1;
  }
}

export function recordAttempt(insights, question, reply, outcome, retrieval, now) {
  const [top] = retrieval.hits;
  insights.attempts.push({
    questionMessageId: question.id,
    replyMessageId: reply?.id ?? null,
    question: question.text,
    outcome,
    confidence: retrieval.confidence,
    sourceId: top?.id ?? null,
    sourceTitle: top?.title ?? null,
    at: now,
  });
}

export function requestHandoff(conversation, decision, triggerMessage, now) {
  addBotMessage(conversation, HANDOFF_NOTICE[decision.primary.reason], now, {
    kind: BOT_REPLY_KIND.HANDOFF_NOTICE,
    confidence: null,
    sources: [],
  });
  addSystemEvent(conversation, SYSTEM_EVENT.HANDOFF_REQUESTED, `Bot stepped aside — ${HANDOFF_REASON_META[decision.primary.reason].label}`, now, {
    reason: decision.primary.reason,
  });
  conversation.handoff = buildHandoffPacket(conversation, decision, { triggerMessage, now, id: nextId('hof') });
  conversation.status = HANDOFF_PENDING;
}

// ─── agent actions ────────────────────────────────────────────────────────────

export function lastOpenQuestion(conversation) {
  const open = conversation.handoff?.openQuestions ?? [];
  if (open.length) return open.at(-1);
  return conversation.messages.findLast((m) => m.sender === SENDER.CUSTOMER)?.text ?? null;
}

export function draftCopilotReply(question) {
  if (!question) return null;
  const retrieval = retrieve(question);
  const [top] = retrieval.hits;
  if (!top || top.score < HANDOFF_POLICY.copilotThreshold) return null;
  return {
    text: top.answer,
    basedOn: truncate(question, 120),
    confidence: top.score,
    sources: retrieval.hits.map(toSourceRef),
  };
}

export function acceptHandoff(conversation, agent, now, { copilot = draftCopilotReply } = {}) {
  assertStatus(conversation, [HANDOFF_PENDING], 'accept a handoff');
  conversation.status = AGENT_ACTIVE;
  conversation.assignee = { id: agent.id, name: agent.name };
  Object.assign(conversation.handoff, { status: HANDOFF_STATUS.ACCEPTED, acceptedAt: now, acceptedBy: conversation.assignee });
  addSystemEvent(conversation, SYSTEM_EVENT.AGENT_JOINED, `${agent.name} joined with the bot’s handoff context`, now, { agentId: agent.id });
  conversation.copilot = copilot(lastOpenQuestion(conversation));
  return conversation;
}

export function takeOver(conversation, agent, now, options) {
  assertStatus(conversation, [BOT_ACTIVE], 'take over');
  const decision = {
    primary: { reason: HANDOFF_REASON.AGENT_INITIATED, detail: `${agent.name} took over from the live bot queue.` },
    signals: [],
  };
  decision.signals.push(decision.primary);
  conversation.handoff = buildHandoffPacket(conversation, decision, { triggerMessage: null, now, id: nextId('hof') });
  conversation.status = HANDOFF_PENDING;
  addSystemEvent(conversation, SYSTEM_EVENT.AGENT_TOOK_OVER, `${agent.name} took over from the bot`, now, { agentId: agent.id });
  return acceptHandoff(conversation, agent, now, options);
}

export function returnToBot(conversation, agent, now) {
  assertStatus(conversation, [AGENT_ACTIVE], 'return to the bot');
  conversation.handoffHistory.push({ ...conversation.handoff, status: HANDOFF_STATUS.RETURNED, returnedAt: now });
  conversation.handoff = null;
  conversation.assignee = null;
  conversation.copilot = null;
  conversation.status = BOT_ACTIVE;
  conversation.insights.failedAttempts = 0;
  addSystemEvent(conversation, SYSTEM_EVENT.RETURNED_TO_BOT, `${agent.name} handed the conversation back to the bot`, now);
  addBotMessage(conversation, 'Thanks for your patience! I’m here if there’s anything else you need.', now, {
    kind: BOT_REPLY_KIND.SMALL_TALK,
    confidence: null,
    sources: [],
  });
  return conversation;
}

export function postAgentMessage(conversation, agent, text, now) {
  assertStatus(conversation, [AGENT_ACTIVE], 'send an agent reply');
  if (conversation.assignee?.id !== agent.id) throw new ApiError(403, 'This conversation is assigned to another agent.');
  addMessage(conversation, { sender: SENDER.AGENT, text, createdAt: now, author: { id: agent.id, name: agent.name } });
  conversation.copilot = null;
  return conversation;
}

export function resolveConversation(conversation, actor, now) {
  assertStatus(conversation, [BOT_ACTIVE, AGENT_ACTIVE], 'resolve');
  conversation.status = RESOLVED;
  conversation.copilot = null;
  addSystemEvent(conversation, SYSTEM_EVENT.RESOLVED, `Resolved by ${actor?.name ?? 'the bot'}`, now);
  return conversation;
}
