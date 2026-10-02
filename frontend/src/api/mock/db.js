import { ADMINS, AGENTS, CUSTOMERS } from './data/people.js';
import { SEED_SCENARIOS } from './data/seedScenarios.js';
import * as engine from './engine/conversationEngine.js';
import { ApiError } from './engine/conversationEngine.js';

// The mock's "tables": customers, agents, admins (like the real backend's), plus conversations.
export const db = {
  customers: CUSTOMERS.map((c) => ({ ...c })),
  agents: AGENTS.map((a) => ({ ...a })),
  admins: ADMINS.map((a) => ({ ...a })),
  conversations: new Map(),
};

export function findCustomer(id) {
  const customer = db.customers.find((c) => c.id === id);
  if (!customer) throw new ApiError(404, `Customer ${id} not found.`);
  return customer;
}

export function findAgent(id) {
  const agent = db.agents.find((a) => a.id === id);
  if (!agent) throw new ApiError(404, `Agent ${id} not found.`);
  return agent;
}

export function findConversation(id) {
  const conversation = db.conversations.get(id);
  if (!conversation) throw new ApiError(404, `Conversation ${id} not found.`);
  return conversation;
}

/** The profile row for a signed-in persona, created on first use (like the API's first sign-in). */
export function profileFor(kind, user) {
  const table = db[`${kind}s`];
  let row = table.find((p) => p.email === user.email);
  if (!row) {
    const prefix = { customer: 'cus', agent: 'agt', admin: 'adm' }[kind];
    row = { id: `${prefix}_${user.sub}`, name: user.name, email: user.email };
    if (kind === 'customer') Object.assign(row, { tier: 'standard', location: '', customerSince: new Date().toISOString().slice(0, 10), lifetimeValue: 0, orderCount: 0, previousConversations: 0 });
    if (kind === 'agent') Object.assign(row, { capacity: 3, active: true });
    table.push(row);
  }
  return row;
}

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
