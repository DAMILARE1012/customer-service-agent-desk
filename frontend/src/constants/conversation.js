// Lifecycle of a conversation. Handoff is a first-class state, not an error:
//
//   bot_active ──(policy trigger)──▶ handoff_pending ──(accept)──▶ agent_active ──▶ resolved
//        ▲                                                             │
//        └────────────────────────(return to bot)─────────────────────┘
export const CONVERSATION_STATUS = Object.freeze({
  BOT_ACTIVE: 'bot_active',
  HANDOFF_PENDING: 'handoff_pending',
  AGENT_ACTIVE: 'agent_active',
  RESOLVED: 'resolved',
});

export const STATUS_META = {
  [CONVERSATION_STATUS.BOT_ACTIVE]: { label: 'Bot handling', tone: 'sky' },
  [CONVERSATION_STATUS.HANDOFF_PENDING]: { label: 'Awaiting agent', tone: 'amber' },
  [CONVERSATION_STATUS.AGENT_ACTIVE]: { label: 'With agent', tone: 'indigo' },
  [CONVERSATION_STATUS.RESOLVED]: { label: 'Resolved', tone: 'emerald' },
};

export const SENDER = Object.freeze({
  CUSTOMER: 'customer',
  BOT: 'bot',
  AGENT: 'agent',
  SYSTEM: 'system',
});

export const SYSTEM_EVENT = Object.freeze({
  HANDOFF_REQUESTED: 'handoff_requested',
  AGENT_JOINED: 'agent_joined',
  AGENT_TOOK_OVER: 'agent_took_over',
  RETURNED_TO_BOT: 'returned_to_bot',
  RESOLVED: 'resolved',
  REOPENED: 'reopened',
});

// How the bot classified its own reply.
export const BOT_REPLY_KIND = Object.freeze({
  ANSWER: 'answer',
  CLARIFY: 'clarify',
  SMALL_TALK: 'small_talk',
  HANDOFF_NOTICE: 'handoff_notice',
});

export const CUSTOMER_TIER_META = {
  standard: { label: 'Standard', tone: 'slate' },
  plus: { label: 'Plus', tone: 'violet' },
  enterprise: { label: 'Enterprise', tone: 'rose' },
};
