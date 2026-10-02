import { CONVERSATION_STATUS } from '../../constants/conversation.js';
import { HANDOFF_POLICY, HANDOFF_REASON_META } from '../../constants/handoff.js';
import { db, findAgent, findConversation, profileFor } from './db.js';
import * as engine from './engine/conversationEngine.js';
import { ApiError } from './engine/conversationEngine.js';
import { customerSummary, customerView } from './engine/customerView.js';
import { toSummary } from './engine/summary.js';

// The same endpoints and access rules as the FastAPI backend (backend/app/api/main.py). The demo
// persona stands in for the verified access token: identity always comes from it, never the body.

const now = () => Date.now();
const has = (user, role) => Boolean(user?.roles.includes(role));
const isStaff = (user) => has(user, 'agent') || has(user, 'admin');

function signedIn(user) {
  if (!user) throw new ApiError(401, 'Sign in required.');
  return user;
}

function asCustomer(user) {
  if (!has(signedIn(user), 'customer') || isStaff(user)) throw new ApiError(403, 'Only customers can do this.');
  return profileFor('customer', user);
}

function asAgent(user) {
  if (!has(signedIn(user), 'agent')) throw new ApiError(403, 'This needs the agent role.');
  const agent = profileFor('agent', user);
  if (!agent.active) throw new ApiError(403, 'Your agent account is disabled. Ask an admin to re-enable it.');
  return agent;
}

function asAdmin(user) {
  if (!has(signedIn(user), 'admin')) throw new ApiError(403, 'This needs the admin role.');
  return profileFor('admin', user);
}

function asStaff(user) {
  if (!isStaff(signedIn(user))) throw new ApiError(403, 'This needs the agent or admin role.');
}

function ownConversation(id, customer) {
  const conversation = db.conversations.get(id);
  if (!conversation || conversation.customer.id !== customer.id) throw new ApiError(404, `Conversation ${id} not found.`);
  return conversation;
}

const activeCount = (agentId) =>
  [...db.conversations.values()].filter((c) => c.status === CONVERSATION_STATUS.AGENT_ACTIVE && c.assignee?.id === agentId).length;

function checkCapacity(agent) {
  if (activeCount(agent.id) >= agent.capacity) throw new ApiError(409, `You’re at capacity (${agent.capacity} active chats). Resolve or return one first.`);
}

function assignedTo(conversation, agent) {
  if (conversation.assignee?.id !== agent.id) throw new ApiError(403, 'This conversation is assigned to another agent.');
}

// ── Admin: runtime handoff policy (same field names as the API; the mock's keyword retriever uses its own scale) ──

const POLICY_FIELDS = {
  noMatchThreshold: { min: 0, max: 1, integer: false, help: 'Below this retrieval score a question counts as outside the knowledge base.' },
  sentimentThreshold: { min: -1, max: 1, integer: false, help: 'At or below this sentiment (−1…1) the customer counts as frustrated and goes to a person.' },
  maxFailedAttempts: { min: 1, max: 10, integer: true, help: 'Turns in a row without a confident answer before the bot stops trying.' },
};
const POLICY_DEFAULTS = Object.fromEntries(Object.keys(POLICY_FIELDS).map((k) => [k, HANDOFF_POLICY[k]]));
const policyMeta = { updatedAt: null, updatedBy: null };

const policy = () => ({
  values: Object.fromEntries(Object.keys(POLICY_FIELDS).map((k) => [k, HANDOFF_POLICY[k]])),
  defaults: POLICY_DEFAULTS,
  fields: POLICY_FIELDS,
  ...policyMeta,
});

function updatePolicy(values, admin) {
  for (const [name, value] of Object.entries(values ?? {})) {
    const field = POLICY_FIELDS[name];
    if (!field) throw new ApiError(400, `Unknown policy setting "${name}".`);
    if (typeof value !== 'number' || (field.integer && !Number.isInteger(value))) throw new ApiError(400, `"${name}" must be ${field.integer ? 'a whole number' : 'a number'}.`);
    if (value < field.min || value > field.max) throw new ApiError(400, `"${name}" must be between ${field.min} and ${field.max}.`);
  }
  Object.assign(HANDOFF_POLICY, values);
  Object.assign(policyMeta, { updatedAt: new Date().toISOString(), updatedBy: admin.name });
  return policy();
}

function insights() {
  const conversations = [...db.conversations.values()];
  const byStatus = Object.fromEntries(Object.values(CONVERSATION_STATUS).map((s) => [s, conversations.filter((c) => c.status === s).length]));
  const reasons = {};
  const waits = [];
  let handedOff = 0;
  for (const c of conversations) {
    const packets = [...c.handoffHistory, ...(c.handoff ? [c.handoff] : [])];
    if (packets.length) handedOff += 1;
    for (const p of packets) {
      reasons[p.reason] = (reasons[p.reason] ?? 0) + 1;
      if (p.acceptedAt) waits.push((p.acceptedAt - p.requestedAt) / 1000);
    }
  }
  const outcomes = {};
  for (const c of conversations) for (const a of c.insights.attempts) outcomes[a.outcome] = (outcomes[a.outcome] ?? 0) + 1;
  const attempts = Object.values(outcomes).reduce((sum, n) => sum + n, 0);
  const resolved = conversations.filter((c) => c.status === CONVERSATION_STATUS.RESOLVED);
  waits.sort((a, b) => a - b);
  return {
    conversations: { total: conversations.length, byStatus },
    handoffs: {
      conversationsHandedOff: handedOff,
      rate: conversations.length ? handedOff / conversations.length : null,
      byReason: Object.entries(reasons)
        .sort((a, b) => b[1] - a[1])
        .map(([reason, count]) => ({ reason, label: HANDOFF_REASON_META[reason]?.label ?? reason, count })),
      medianWaitSeconds: waits.length ? waits[Math.floor(waits.length / 2)] : null,
    },
    bot: {
      questions: attempts,
      answerRate: attempts ? (outcomes.answered ?? 0) / attempts : null,
      outcomes,
      resolvedWithoutAgent: resolved.filter((c) => !c.handoffHistory.length && !c.handoff).length,
      resolved: resolved.length,
    },
    evaluation: { retrieval: null, endToEnd: null }, // offline eval reports exist only on the real backend
    links: null,
  };
}

const sortRecent = (list) => list.sort((a, b) => b.updatedAt - a.updatedAt);

const routes = [
  // Everyone
  ['GET', /^\/me$/, (_, __, user) => {
    signedIn(user);
    const me = { user: { sub: user.sub, username: user.username, name: user.name, email: user.email, roles: [...user.roles].sort() } };
    if (has(user, 'customer') && !isStaff(user)) me.customer = profileFor('customer', user);
    if (has(user, 'agent')) me.agent = profileFor('agent', user);
    if (has(user, 'admin')) me.admin = profileFor('admin', user);
    return me;
  }],

  // Customers
  ['GET', /^\/me\/conversations$/, (_, __, user) => {
    const customer = asCustomer(user);
    return sortRecent([...db.conversations.values()].filter((c) => c.customer.id === customer.id)).map(customerSummary);
  }],
  ['POST', /^\/me\/conversations$/, (_, __, user) => {
    const conversation = engine.createConversation(asCustomer(user), now());
    db.conversations.set(conversation.id, conversation);
    return customerView(conversation);
  }],
  ['GET', /^\/me\/conversations\/([\w-]+)$/, ([id], __, user) => customerView(ownConversation(id, asCustomer(user)))],
  ['POST', /^\/me\/conversations\/([\w-]+)\/messages$/, ([id], body, user) => {
    const conversation = ownConversation(id, asCustomer(user));
    if (!body?.text?.trim()) throw new ApiError(400, '"text" field required.');
    return customerView(engine.receiveCustomerMessage(conversation, body.text.trim(), now()));
  }],

  // Agents
  ['GET', /^\/customers$/, (_, __, user) => (asStaff(user), db.customers)],
  ['GET', /^\/conversations$/, (_, __, user) => {
    const agent = asAgent(user);
    return [...db.conversations.values()].filter((c) => c.status !== CONVERSATION_STATUS.RESOLVED || c.assignee?.id === agent.id).map(toSummary);
  }],
  ['GET', /^\/conversations\/([\w-]+)$/, ([id], __, user) => (asStaff(user), findConversation(id))],
  ['POST', /^\/conversations\/([\w-]+)\/agent-messages$/, ([id], body, user) => engine.postAgentMessage(findConversation(id), asAgent(user), body.text, now())],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/accept$/, ([id], __, user) => {
    const agent = asAgent(user);
    const conversation = findConversation(id);
    checkCapacity(agent);
    return engine.acceptHandoff(conversation, agent, now());
  }],
  ['POST', /^\/conversations\/([\w-]+)\/handoff\/return$/, ([id], __, user) => {
    const agent = asAgent(user);
    const conversation = findConversation(id);
    assignedTo(conversation, agent);
    return engine.returnToBot(conversation, agent, now());
  }],
  ['POST', /^\/conversations\/([\w-]+)\/takeover$/, ([id], __, user) => {
    const agent = asAgent(user);
    checkCapacity(agent);
    return engine.takeOver(findConversation(id), agent, now());
  }],
  ['POST', /^\/conversations\/([\w-]+)\/resolve$/, ([id], __, user) => {
    const agent = asAgent(user);
    const conversation = findConversation(id);
    if (conversation.status === CONVERSATION_STATUS.AGENT_ACTIVE) assignedTo(conversation, agent);
    return engine.resolveConversation(conversation, agent, now());
  }],

  // Admins
  ['GET', /^\/admin\/agents$/, (_, __, user) => (asAdmin(user), db.agents.map((a) => ({ ...a, activeChats: activeCount(a.id), signedInOnce: true })))],
  ['PATCH', /^\/admin\/agents\/([\w-]+)$/, ([id], body, user) => {
    asAdmin(user);
    const agent = findAgent(id);
    if (body.capacity != null && (body.capacity < 1 || body.capacity > 20)) throw new ApiError(400, '"capacity" must be between 1 and 20.');
    Object.assign(agent, body.capacity != null && { capacity: body.capacity }, body.active != null && { active: body.active });
    return { ...agent, activeChats: activeCount(agent.id), signedInOnce: true };
  }],
  ['GET', /^\/admin\/conversations$/, (_, __, user, params = {}) => {
    asAdmin(user);
    const term = (params.q ?? '').trim().toLowerCase();
    const rows = [...db.conversations.values()].filter(
      (c) =>
        (!params.status || c.status === params.status) &&
        (!params.agentId || c.assignee?.id === params.agentId) &&
        (!term || c.customer.name.toLowerCase().includes(term) || (c.subject ?? '').toLowerCase().includes(term)),
    );
    return sortRecent(rows).map(toSummary);
  }],
  ['GET', /^\/admin\/policy$/, (_, __, user) => (asAdmin(user), policy())],
  ['PUT', /^\/admin\/policy$/, (_, body, user) => updatePolicy(body, asAdmin(user))],
  ['POST', /^\/admin\/policy\/reset$/, (_, __, user) => updatePolicy(POLICY_DEFAULTS, asAdmin(user))],
  ['GET', /^\/admin\/insights$/, (_, __, user) => (asAdmin(user), insights())],
];

export function handleRequest({ url, method = 'GET', body, params }, user) {
  const [path, query] = url.split('?');
  const allParams = { ...Object.fromEntries(new URLSearchParams(query ?? '')), ...params };
  for (const [routeMethod, pattern, handler] of routes) {
    if (routeMethod !== method.toUpperCase()) continue;
    const match = path.match(pattern);
    if (match) return handler(match.slice(1), body, user, allParams);
  }
  throw new ApiError(404, `No mock route for ${method} ${path}`);
}
