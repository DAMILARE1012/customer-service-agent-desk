import { CUSTOMER_TIER_META } from '../../../constants/conversation.js';
import { HANDOFF_REASON, HANDOFF_REASON_META, HANDOFF_STATUS } from '../../../constants/handoff.js';
import { computePriority } from './handoffPolicy.js';
import { sentimentLabel } from './sentiment.js';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// In production this would be an LLM summarisation call over the transcript + retrieval trace.
function buildSummary({ customer, insights }, primary) {
  const { attempts, entities, intent } = insights;
  const answered = attempts.filter((a) => a.outcome === 'answered');
  const open = attempts.filter((a) => a.outcome !== 'answered');
  const tier = CUSTOMER_TIER_META[customer.tier]?.label ?? customer.tier;

  return [
    `${customer.name} (${tier} customer) reached out${intent ? ` about ${intent.label.toLowerCase()}` : ''}.`,
    answered.length
      ? `The bot answered ${plural(answered.length, 'question')} from the help centre (${[...new Set(answered.map((a) => a.sourceTitle))].join(', ')}).`
      : 'The bot was not able to answer anything confidently.',
    open.length ? `${plural(open.length, 'question')} still open.` : null,
    entities.length ? `Shared: ${entities.map((e) => `${e.label.toLowerCase()} ${e.value}`).join(', ')}.` : null,
    `Stepped aside because: ${primary.detail}`,
  ]
    .filter(Boolean)
    .join(' ');
}

const REASON_STEPS = {
  [HANDOFF_REASON.CUSTOMER_REQUEST]: ['Greet them by name and confirm you already have the context — don’t make them repeat themselves.'],
  [HANDOFF_REASON.SENSITIVE_TOPIC]: [
    'Verify identity before discussing account or payment details.',
    'Follow the escalation playbook for this topic; avoid commitments the bot could not make.',
  ],
  [HANDOFF_REASON.NEGATIVE_SENTIMENT]: [
    'Acknowledge the frustration before troubleshooting.',
    'Consider a goodwill gesture if policy allows.',
  ],
  [HANDOFF_REASON.REPEATED_FAILURE]: [
    'Don’t repeat the bot’s earlier answers — they didn’t land.',
    'Ask one targeted question to pin down what they need.',
  ],
  [HANDOFF_REASON.LOW_CONFIDENCE]: [
    'The knowledge base had no good match — clarify the request directly.',
    'Flag a KB gap if this comes up often.',
  ],
  [HANDOFF_REASON.AGENT_INITIATED]: ['Review the bot’s last answer before replying.'],
  [HANDOFF_REASON.ASSISTANT_UNAVAILABLE]: ['The assistant could not answer (model error or timeout) — the question itself may be simple.'],
};

function buildNextSteps(primary, entities) {
  const steps = [...(REASON_STEPS[primary.reason] ?? [])];
  const order = entities.find((e) => e.type === 'order_id');
  if (order) steps.push(`Look up order ${order.value} in the order system.`);
  const amount = entities.find((e) => e.type === 'amount');
  if (amount) steps.push(`Confirm the ${amount.value} charge against billing records.`);
  return steps;
}

const MIN_SOURCE_SCORE = 0.35;

function collectSources(conversation) {
  const byId = new Map();
  for (const message of conversation.messages) {
    for (const source of message.meta?.sources ?? []) {
      if (source.score < MIN_SOURCE_SCORE) continue;
      const current = byId.get(source.id);
      if (!current || source.score > current.score) byId.set(source.id, { ...source, citedInMessageId: message.id });
    }
  }
  return [...byId.values()].sort((a, b) => b.score - a.score).slice(0, 5);
}

/** Snapshot of everything the bot knows, frozen at the moment it stepped aside. */
export function buildHandoffPacket(conversation, decision, { triggerMessage, now, id }) {
  const { insights, customer } = conversation;
  const { primary, signals } = decision;
  const current = insights.sentiment.current;

  return {
    id,
    status: HANDOFF_STATUS.PENDING,
    reason: primary.reason,
    reasonLabel: HANDOFF_REASON_META[primary.reason].label,
    reasonDetail: primary.detail,
    signals,
    priority: computePriority({ reason: primary.reason, sentiment: current, tier: customer.tier }),
    requestedAt: now,
    acceptedAt: null,
    acceptedBy: null,
    triggerMessage: triggerMessage ? { id: triggerMessage.id, text: triggerMessage.text } : null,
    summary: buildSummary(conversation, primary),
    intent: insights.intent,
    entities: insights.entities,
    botAttempts: insights.attempts,
    openQuestions: insights.attempts.filter((a) => a.outcome !== 'answered').map((a) => a.question),
    sources: collectSources(conversation),
    sentiment: { current, label: sentimentLabel(current), trend: insights.sentiment.trend },
    suggestedNextSteps: buildNextSteps(primary, insights.entities),
  };
}
