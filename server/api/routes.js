import { ApiError } from '../../src/api/mock/engine/conversationEngine.js';
import { toSummary } from '../../src/api/mock/engine/summary.js';
import * as engine from '../conversation/engine.js';
import {
  allConversations,
  findAgent,
  findConversation,
  findCustomer,
  listCustomers,
  saveConversation,
  withConversationLock,
} from '../conversation/store.js';

// The same REST contract as the in-browser mock (src/api/mock/routes.js), so the desk switches
// to this backend by setting VITE_API_URL — nothing else changes.

const now = () => Date.now();
const agentFrom = (body) => findAgent(body?.agentId);

function requireText(body) {
  const text = typeof body?.text === 'string' ? body.text.trim() : '';
  if (!text) throw new ApiError(400, '"text" is required.');
  if (text.length > 4000) throw new ApiError(413, 'Message is too long (max 4,000 characters).');
  return text;
}

/** Operations on one conversation run one at a time, in order. */
const onConversation = (fn) => ([id], body) => withConversationLock(id, () => fn(findConversation(id), body));

// [method, pattern, route name (Prometheus label — never the raw path), handler]
export const routes = [
  ['GET', /^\/customers$/, 'customers', () => listCustomers()],
  ['GET', /^\/conversations$/, 'conversations', () => allConversations().map(toSummary)],
  ['GET', /^\/conversations\/([\w-]+)$/, 'conversation', ([id]) => findConversation(id)],
  [
    'POST',
    /^\/conversations$/,
    'create_conversation',
    (_, body) => {
      const conversation = engine.createConversation(findCustomer(body?.customerId), now());
      saveConversation(conversation);
      return conversation;
    },
  ],
  ['POST', /^\/conversations\/([\w-]+)\/customer-messages$/, 'customer_message', onConversation((c, body) => engine.receiveCustomerMessage(c, requireText(body), now()))],
  ['POST', /^\/conversations\/([\w-]+)\/agent-messages$/, 'agent_message', onConversation((c, body) => engine.postAgentMessage(c, agentFrom(body), requireText(body), now()))],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/accept$/, 'accept_handoff', onConversation((c, body) => engine.acceptHandoff(c, agentFrom(body), now()))],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/return$/, 'return_to_bot', onConversation((c, body) => engine.returnToBot(c, agentFrom(body), now()))],
  ['POST', /^\/conversations\/([\w-]+)\/takeover$/, 'take_over', onConversation((c, body) => engine.takeOver(c, agentFrom(body), now()))],
  [
    'POST',
    /^\/conversations\/([\w-]+)\/resolve$/,
    'resolve',
    onConversation((c, body) => engine.resolveConversation(c, body?.agentId ? agentFrom(body) : null, now())),
  ],
];

export function matchRoute(method, pathname) {
  for (const [routeMethod, pattern, name, handler] of routes) {
    if (routeMethod !== method) continue;
    const match = pathname.match(pattern);
    if (match) return { name, handler, params: match.slice(1) };
  }
  return null;
}
