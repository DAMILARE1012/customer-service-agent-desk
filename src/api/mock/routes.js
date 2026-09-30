import { db, findAgent, findConversation, findCustomer, listCustomers } from './db.js';
import * as engine from './engine/conversationEngine.js';
import { ApiError } from './engine/conversationEngine.js';
import { toSummary } from './engine/summary.js';

const now = () => Date.now();
const agentFrom = (body) => findAgent(body?.agentId);

const routes = [
  ['GET', /^\/customers$/, () => listCustomers()],
  ['GET', /^\/conversations$/, () => [...db.conversations.values()].map(toSummary)],
  ['GET', /^\/conversations\/([\w-]+)$/, ([id]) => findConversation(id)],
  [
    'POST',
    /^\/conversations$/,
    (_, body) => {
      const conversation = engine.createConversation(findCustomer(body.customerId), now());
      db.conversations.set(conversation.id, conversation);
      return conversation;
    },
  ],
  [
    'POST',
    /^\/conversations\/([\w-]+)\/customer-messages$/,
    ([id], body) => engine.receiveCustomerMessage(findConversation(id), body.text, now()),
  ],
  [
    'POST',
    /^\/conversations\/([\w-]+)\/agent-messages$/,
    ([id], body) => engine.postAgentMessage(findConversation(id), agentFrom(body), body.text, now()),
  ],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/accept$/, ([id], body) => engine.acceptHandoff(findConversation(id), agentFrom(body), now())],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/return$/, ([id], body) => engine.returnToBot(findConversation(id), agentFrom(body), now())],
  ['POST', /^\/conversations\/([\w-]+)\/takeover$/, ([id], body) => engine.takeOver(findConversation(id), agentFrom(body), now())],
  [
    'POST',
    /^\/conversations\/([\w-]+)\/resolve$/,
    ([id], body) => engine.resolveConversation(findConversation(id), body?.agentId ? agentFrom(body) : null, now()),
  ],
];

export function handleRequest({ url, method = 'GET', body }) {
  for (const [routeMethod, pattern, handler] of routes) {
    if (routeMethod !== method.toUpperCase()) continue;
    const match = url.match(pattern);
    if (match) return handler(match.slice(1), body);
  }
  throw new ApiError(404, `No mock route for ${method} ${url}`);
}
