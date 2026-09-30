import { AGENTS, CUSTOMERS } from '../../src/api/mock/data/people.js';
import { ApiError } from '../../src/api/mock/engine/conversationEngine.js';
import { CONVERSATION_STATUS } from '../../src/constants/conversation.js';
import { config } from '../config.js';

// In-memory store. Conversations live for the life of the process — swap for a database by
// keeping this module's interface.

const conversations = new Map();

export const listCustomers = () => CUSTOMERS;

export function findCustomer(id) {
  const customer = CUSTOMERS.find((c) => c.id === id);
  if (!customer) throw new ApiError(404, `Customer ${id} not found.`);
  return customer;
}

export function findAgent(id) {
  const agent = AGENTS.find((a) => a.id === id);
  if (!agent) throw new ApiError(404, `Agent ${id} not found.`);
  return agent;
}

export const allConversations = () => [...conversations.values()];
export const saveConversation = (conversation) => conversations.set(conversation.id, conversation);

export function findConversation(id) {
  const conversation = conversations.get(id);
  if (!conversation) throw new ApiError(404, `Conversation ${id} not found.`);
  return conversation;
}

// Bot turns await the LLM, so two messages for the same conversation could interleave.
// Each conversation gets a queue: operations on it run one at a time, in arrival order.
const tails = new Map();

export function withConversationLock(id, fn) {
  const run = (tails.get(id) ?? Promise.resolve()).then(() => fn());
  const tail = run.catch(() => {});
  tails.set(id, tail);
  tail.then(() => {
    if (tails.get(id) === tail) tails.delete(id);
  });
  return run;
}

/** Live desk numbers for the Prometheus gauges. */
export function deskStats(now = Date.now()) {
  const byStatus = Object.fromEntries(Object.values(CONVERSATION_STATUS).map((status) => [status, 0]));
  let oldestHandoffWaitSeconds = 0;
  let slaBreaches = 0;
  for (const conversation of conversations.values()) {
    byStatus[conversation.status] += 1;
    if (conversation.status !== CONVERSATION_STATUS.HANDOFF_PENDING) continue;
    const waited = now - conversation.handoff.requestedAt;
    oldestHandoffWaitSeconds = Math.max(oldestHandoffWaitSeconds, waited / 1000);
    if (waited >= config.sla.breachAfterMs) slaBreaches += 1;
  }
  return { byStatus, oldestHandoffWaitSeconds, slaBreaches };
}
