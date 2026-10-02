import { config } from '../config.js';

export const HANDOFF_REASON = Object.freeze({
  SENSITIVE_TOPIC: 'sensitive_topic',
  CUSTOMER_REQUEST: 'customer_request',
  NEGATIVE_SENTIMENT: 'negative_sentiment',
  REPEATED_FAILURE: 'repeated_failure',
  LOW_CONFIDENCE: 'low_confidence',
  AGENT_INITIATED: 'agent_initiated',
  ASSISTANT_UNAVAILABLE: 'assistant_unavailable', // the LLM failed or timed out — degrade to a human, never to an error
});

// When several signals fire on the same turn, the first one here becomes the primary reason.
export const HANDOFF_PRECEDENCE = [
  HANDOFF_REASON.SENSITIVE_TOPIC,
  HANDOFF_REASON.CUSTOMER_REQUEST,
  HANDOFF_REASON.NEGATIVE_SENTIMENT,
  HANDOFF_REASON.REPEATED_FAILURE,
  HANDOFF_REASON.LOW_CONFIDENCE,
  HANDOFF_REASON.ASSISTANT_UNAVAILABLE,
];

export const HANDOFF_REASON_META = {
  [HANDOFF_REASON.SENSITIVE_TOPIC]: {
    label: 'Sensitive topic',
    description: 'Policy requires a human for this subject.',
    icon: 'shield',
    tone: 'rose',
  },
  [HANDOFF_REASON.CUSTOMER_REQUEST]: {
    label: 'Asked for a human',
    description: 'The customer explicitly asked to speak with a person.',
    icon: 'user',
    tone: 'indigo',
  },
  [HANDOFF_REASON.NEGATIVE_SENTIMENT]: {
    label: 'Customer frustrated',
    description: 'Sentiment dropped below the handoff threshold.',
    icon: 'frown',
    tone: 'amber',
  },
  [HANDOFF_REASON.REPEATED_FAILURE]: {
    label: 'Bot not getting there',
    description: 'Several turns in a row without a confident answer.',
    icon: 'refresh',
    tone: 'amber',
  },
  [HANDOFF_REASON.LOW_CONFIDENCE]: {
    label: 'Outside knowledge base',
    description: 'Nothing in the knowledge base matched well enough to answer.',
    icon: 'question',
    tone: 'sky',
  },
  [HANDOFF_REASON.AGENT_INITIATED]: {
    label: 'Agent took over',
    description: 'An agent stepped in from the live bot queue.',
    icon: 'arrowRight',
    tone: 'violet',
  },
  [HANDOFF_REASON.ASSISTANT_UNAVAILABLE]: {
    label: 'Assistant unavailable',
    description: 'The language model failed or timed out, so the bot stepped aside.',
    icon: 'warning',
    tone: 'rose',
  },
};

export const HANDOFF_STATUS = Object.freeze({
  PENDING: 'pending',
  ACCEPTED: 'accepted',
  RETURNED: 'returned',
  ABANDONED: 'abandoned', // the customer left before an agent picked it up
});

export const PRIORITY = Object.freeze({
  URGENT: 'urgent',
  HIGH: 'high',
  NORMAL: 'normal',
});

export const PRIORITY_META = {
  [PRIORITY.URGENT]: { label: 'Urgent', tone: 'rose', rank: 0 },
  [PRIORITY.HIGH]: { label: 'High', tone: 'amber', rank: 1 },
  [PRIORITY.NORMAL]: { label: 'Normal', tone: 'slate', rank: 2 },
};

// Wait-time thresholds (ms) for the SLA colouring in the queue. Set in .env.
export const HANDOFF_SLA = config.sla;

// Every threshold that decides "should the bot step aside?" — set in .env (see .env.example).
// Shared so the desk can show how close a live conversation is to a handoff.
export const HANDOFF_POLICY = config.handoffPolicy;
