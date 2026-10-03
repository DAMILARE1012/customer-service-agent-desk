import { BOT_REPLY_KIND, CLOSED_REASON, CONVERSATION_STATUS, SENDER, SYSTEM_EVENT } from '../../../constants/conversation.js';
import { HANDOFF_REASON, HANDOFF_REASON_META, HANDOFF_STATUS } from '../../../constants/handoff.js';
import { extractEntities, mergeEntities } from './entities.js';
import { buildHandoffPacket } from './handoffPacket.js';
import { HANDOFF_POLICY, SENSITIVE_TOPICS, computePriority, detectSmallTalk, evaluateHandoff } from './handoffPolicy.js';
import { retrieve, toSourceRef } from './retrieval.js';
import { scoreSentiment, sentimentLabel } from './sentiment.js';
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

export function createConversation(customer, now, followUpOf = null) {
  return {
    id: nextId('conv'),
    customer,
    status: BOT_ACTIVE,
    assignee: null,
    subject: null,
    createdAt: now,
    updatedAt: now,
    closedAt: null,
    closedReason: null,
    followUpOf, // snapshot of the closed session this continues — for agents, never replayed to the bot
    customerSeenAt: now,
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
    // Sessions don't reopen: a returning customer starts fresh (optionally as a linked follow-up).
    throw new ApiError(409, 'This conversation has ended. Start a new one — you can link it to this one as a follow-up.');
  }
  conversation.customerSeenAt = now;

  const message = addMessage(conversation, { sender: SENDER.CUSTOMER, text, createdAt: now });
  conversation.subject ??= truncate(text, 70);
  const sentiment = trackSignals(conversation, message);

  if (conversation.status === BOT_ACTIVE) runBotTurn(conversation, message, sentiment, now);
  else if (conversation.status === AGENT_ACTIVE) conversation.copilot = draftCopilotReply(text);
  else if (conversation.status === HANDOFF_PENDING) noteWhileWaiting(conversation, message, sentiment, now);

  return conversation;
}

const PRIORITY_RANK = { normal: 0, high: 1, urgent: 2 };
export const WAITING_ACK = 'Thanks — I’ve added that to your request, so the team will see it as soon as they join. Add anything else that might help.';

/** A message while the handoff waits: the bot stays quiet, the brief stays current, urgency only goes up. */
function noteWhileWaiting(conversation, message, sentiment, now) {
  const { handoff, insights } = conversation;
  const added = [...(handoff.addedWhileWaiting ?? []), { id: message.id, text: message.text, at: now }];
  Object.assign(handoff, {
    addedWhileWaiting: added,
    entities: insights.entities,
    sentiment: { current: sentiment, label: sentimentLabel(sentiment), trend: insights.sentiment.trend },
  });
  const sensitive = SENSITIVE_TOPICS.find(({ pattern }) => pattern.test(message.text));
  const priority = computePriority({ reason: sensitive ? HANDOFF_REASON.SENSITIVE_TOPIC : handoff.reason, sentiment, tier: conversation.customer.tier });
  if (PRIORITY_RANK[priority] > PRIORITY_RANK[handoff.priority]) {
    const why = sensitive ? `${sensitive.topic} — policy requires a human.` : `Sentiment fell to ${sentiment.toFixed(2)} while waiting.`;
    Object.assign(handoff, { priority, escalated: { from: handoff.priority, to: priority, why, at: now } });
    addSystemEvent(conversation, SYSTEM_EVENT.PRIORITY_RAISED, `Priority raised to ${priority} — ${why}`, now, { priority });
  }
  if (added.length === 1) addBotMessage(conversation, WAITING_ACK, now, { kind: BOT_REPLY_KIND.SMALL_TALK, confidence: null, sources: [] });
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
  const added = conversation.handoff?.addedWhileWaiting ?? [];
  if (added.length) return added.at(-1).text;
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
  addSystemEvent(conversation, SYSTEM_EVENT.AGENT_JOINED, `${agent.name} joined with the bot’s handoff context`, now, { agentId: agent.id, agentName: agent.name });
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

export const SESSION_IDLE_MINUTES = 30;
export const SESSION_ABANDON_MINUTES = 10;

const CLOSED_NOTE = {
  [CLOSED_REASON.RESOLVED]: (actor) => `Resolved by ${actor?.name ?? 'the bot'}`,
  [CLOSED_REASON.ENDED_BY_CUSTOMER]: () => 'The customer ended the chat',
  [CLOSED_REASON.INACTIVE]: () => `Closed after ${SESSION_IDLE_MINUTES} minutes without activity`,
  [CLOSED_REASON.ABANDONED]: () => 'The customer left before an agent joined',
};

/** End the session for good. A handoff still waiting is marked abandoned, not left in the queue. */
export function closeConversation(conversation, reason, now, actor = null) {
  assertStatus(conversation, [BOT_ACTIVE, HANDOFF_PENDING, AGENT_ACTIVE], 'close the conversation');
  if (conversation.status === HANDOFF_PENDING && conversation.handoff) conversation.handoff.status = HANDOFF_STATUS.ABANDONED;
  Object.assign(conversation, { status: RESOLVED, copilot: null, closedReason: reason, closedAt: now });
  addSystemEvent(conversation, SYSTEM_EVENT.RESOLVED, CLOSED_NOTE[reason](actor), now, { closedReason: reason });
  return conversation;
}

export function resolveConversation(conversation, actor, now) {
  assertStatus(conversation, [BOT_ACTIVE, AGENT_ACTIVE], 'resolve');
  return closeConversation(conversation, CLOSED_REASON.RESOLVED, now, actor);
}

const lastCustomerMessageAt = (c) => c.messages.filter((m) => m.sender === SENDER.CUSTOMER).at(-1)?.createdAt ?? c.createdAt;

/** Same rules as the API's session sweeper (backend/app/conversation/sessions.py). */
export function dueForClosing(conversation, now) {
  const idleMs = SESSION_IDLE_MINUTES * 60_000;
  if (conversation.status === BOT_ACTIVE) return now - lastCustomerMessageAt(conversation) >= idleMs ? CLOSED_REASON.INACTIVE : null;
  if (conversation.status === AGENT_ACTIVE) return now - conversation.updatedAt >= idleMs ? CLOSED_REASON.INACTIVE : null;
  if (conversation.status === HANDOFF_PENDING) {
    const seen = Math.max(conversation.customerSeenAt ?? 0, lastCustomerMessageAt(conversation));
    return now - seen >= SESSION_ABANDON_MINUTES * 60_000 ? CLOSED_REASON.ABANDONED : null;
  }
  return null;
}
