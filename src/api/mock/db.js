import { AGENTS, CUSTOMERS } from './data/people.js';
import { SEED_SCENARIOS } from './data/seedScenarios.js';
import * as engine from './engine/conversationEngine.js';
import { ApiError } from './engine/conversationEngine.js';

export const db = {
  conversations: new Map(),
};

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

export function findConversation(id) {
  const conversation = db.conversations.get(id);
  if (!conversation) throw new ApiError(404, `Conversation ${id} not found.`);
  return conversation;
}

export const listCustomers = () => CUSTOMERS;

function seed() {
  const start = Date.now();
  for (const { customerId, steps } of SEED_SCENARIOS) {
    const at = (minutesAgo) => start - minutesAgo * 60_000;
    const conversation = engine.createConversation(findCustomer(customerId), at(steps[0][0]));

    for (const [minutesAgo, action, ...args] of steps) {
      const now = at(minutesAgo);
      if (action === 'customer') engine.receiveCustomerMessage(conversation, args[0], now);
      if (action === 'accept') engine.acceptHandoff(conversation, findAgent(args[0]), now);
      if (action === 'agent') engine.postAgentMessage(conversation, findAgent(args[0]), args[1], now);
      if (action === 'resolve') engine.resolveConversation(conversation, null, now);
    }
    db.conversations.set(conversation.id, conversation);
  }
}

seed();
