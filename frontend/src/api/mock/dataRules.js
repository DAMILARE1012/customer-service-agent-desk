import { CLOSED_REASON, CONVERSATION_STATUS, SENDER } from '../../constants/conversation.js';
import { HANDOFF_POLICY } from '../../constants/handoff.js';
import { db } from './db.js';
import { ApiError } from './engine/conversationEngine.js';

// Demo-mode stand-ins for the API's data rules and review pipeline (backend/app/privacy, app/review,
// app/audit.py): same endpoints and shapes, simpler internals (no embeddings, no files written).

export const RETENTION_DAYS = 365;
export const privacyNotice = () => ({
  retentionDays: RETENTION_DAYS,
  notice: `Conversations are kept for ${RETENTION_DAYS} days so our support team can help you, then their text is deleted. Team members can read this chat; personal details are removed before we use conversations to improve our help centre.`,
});

db.audit = [];
db.review = new Map();
const recentViews = new Map();

export function audit(user, action, { conversationId = null, customerId = null, detail = {} } = {}) {
  if (action.endsWith('.view')) {
    const key = `${user.sub}|${action}|${conversationId ?? customerId}`;
    if (Date.now() - (recentViews.get(key) ?? 0) < 10 * 60_000) return;
    recentViews.set(key, Date.now());
  }
  const role = user.roles.includes('admin') ? 'admin' : 'agent';
  db.audit.unshift({ id: db.audit.length + 1, at: new Date().toISOString(), actorId: user.sub, actorName: user.name, actorRole: role, action, conversationId, customerId, detail });
}

// ── Redaction (a subset of backend/app/privacy/redact.py) ──
export function redact(text, names = []) {
  let out = text
    .replace(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, '[EMAIL]')
    .replace(/\b(order|invoice|ticket|case)(\s*(?:no\.?|number|#)?\s*)#?\s*\d{4,}\b/gi, '$1 [ORDER]')
    .replace(/#\d{4,}\b/g, '[ORDER]');
  for (const name of names.filter((n) => n && n.length >= 2).sort((a, b) => b.length - a.length)) {
    out = out.replace(new RegExp(`\\b${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'gi'), '[NAME]');
  }
  return out;
}

const namesOf = (c) => [c.customer.name, ...c.customer.name.split(/\s+/)];
const topic = (q) => q.toLowerCase().replace(/[^a-z0-9 ]/g, '').split(/\s+/).filter((w) => w.length > 3).slice(0, 4).sort().join(' ');
const nextId = () => `rev_${Math.random().toString(16).slice(2, 12)}`;

function gapQuestions(c) {
  const packets = [...c.handoffHistory, ...(c.handoff ? [c.handoff] : [])];
  const struggled = packets.some((p) => p.reason === 'repeated_failure');
  return [...new Set(c.insights.attempts.filter((a) => a.outcome !== 'answered' && (a.confidence < HANDOFF_POLICY.answerThreshold || struggled) && a.question.split(/\s+/).length >= 4).map((a) => a.question))];
}

function testQuestion(c) {
  if (c.closedReason !== CLOSED_REASON.RESOLVED) return null;
  const packet = [...c.handoffHistory, ...(c.handoff ? [c.handoff] : [])].filter((p) => p.acceptedAt).at(-1);
  const replies = c.messages.filter((m) => m.sender === SENDER.AGENT).map((m) => m.text);
  const question = packet?.triggerMessage?.text ?? packet?.openQuestions?.at(-1) ?? '';
  if (!packet || !replies.length || question.split(/\s+/).length < 4) return null;
  return [question, replies.join('\n\n').slice(0, 1500)];
}

export function runReview() {
  const items = [...db.review.values()];
  const totals = { conversations: 0, gapsNew: 0, gapsUpdated: 0, testQuestions: 0 };
  for (const c of db.conversations.values()) {
    if (c.status !== CONVERSATION_STATUS.RESOLVED || c.reviewedAt) continue;
    totals.conversations += 1;
    const names = namesOf(c);
    const replies = c.messages.filter((m) => m.sender === SENDER.AGENT).map((m) => redact(m.text, names).slice(0, 400)).slice(0, 2);
    for (const raw of gapQuestions(c)) {
      const question = redact(raw, names);
      const match = items.find((i) => i.kind === 'knowledge_gap' && i.topic === topic(question));
      if (match) {
        match.count += 1;
        if (!match.examples.includes(question) && match.examples.length < 5) match.examples.push(question);
        match.agentAnswers = [...new Set([...match.agentAnswers, ...replies])].slice(0, 3);
        match.conversationIds = [...new Set([...match.conversationIds, c.id])];
        totals.gapsUpdated += 1;
      } else {
        const item = { id: nextId(), kind: 'knowledge_gap', status: 'pending', question, answer: '', title: '', examples: [question], agentAnswers: replies, conversationIds: [c.id], count: 1, topic: topic(question), publishedPath: null, createdAt: new Date().toISOString() };
        db.review.set(item.id, item);
        items.push(item);
        totals.gapsNew += 1;
      }
    }
    const pair = testQuestion(c);
    if (pair) {
      const [question, answer] = [redact(pair[0], names), redact(pair[1], names)];
      if (!items.some((i) => i.kind === 'test_question' && i.topic === topic(question))) {
        const item = { id: nextId(), kind: 'test_question', status: 'pending', question, answer, title: '', examples: [question], agentAnswers: [], conversationIds: [c.id], count: 1, topic: topic(question), publishedPath: null, createdAt: new Date().toISOString() };
        db.review.set(item.id, item);
        items.push(item);
        totals.testQuestions += 1;
      }
    }
    c.reviewedAt = Date.now();
  }
  return totals;
}

const reviewItem = (id) => {
  const item = db.review.get(id);
  if (!item) throw new ApiError(404, `Review item ${id} not found.`);
  return item;
};
const publicItem = ({ topic: _topic, ...item }) => item;

export function reviewRoutes(asAdmin) {
  const slug = (title) => title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'article';
  return [
    ['GET', /^\/admin\/review$/, (_, __, user, params = {}) => {
      asAdmin(user);
      return [...db.review.values()].filter((i) => (!params.kind || i.kind === params.kind) && (!params.status || i.status === params.status)).sort((a, b) => b.count - a.count).map(publicItem);
    }],
    ['POST', /^\/admin\/review\/run$/, (_, __, user) => {
      asAdmin(user);
      const report = runReview();
      audit(user, 'review.run', { detail: report });
      return report;
    }],
    ['PATCH', /^\/admin\/review\/([\w-]+)$/, ([id], body, user) => {
      asAdmin(user);
      const item = reviewItem(id);
      if (['published', 'approved'].includes(item.status)) throw new ApiError(409, 'This item has already been published or approved.');
      for (const key of ['title', 'question', 'answer']) if (body?.[key] != null) item[key] = body[key];
      return publicItem(item);
    }],
    ['POST', /^\/admin\/review\/([\w-]+)\/(publish|approve|reject)$/, ([id, action], __, user) => {
      const admin = asAdmin(user);
      const item = reviewItem(id);
      if (action === 'publish') {
        if (item.kind !== 'knowledge_gap') throw new ApiError(400, 'Only knowledge gaps become articles.');
        if (!item.title.trim() || item.answer.trim().length < 40) throw new ApiError(400, 'Give the article a title and at least a few sentences before publishing.');
        Object.assign(item, { status: 'published', publishedPath: `help-center/${slug(item.title)}.md` });
      } else if (action === 'approve') {
        if (item.kind !== 'test_question') throw new ApiError(400, 'Only test questions can be approved into the evaluation set.');
        item.status = 'approved';
      } else {
        item.status = 'rejected';
      }
      Object.assign(item, { reviewedBy: admin.name, reviewedAt: new Date().toISOString() });
      audit(user, `review.${action}`, { detail: { itemId: id, path: item.publishedPath } });
      return publicItem(item);
    }],
    ['POST', /^\/admin\/knowledge\/reindex$/, (_, __, user) => {
      asAdmin(user);
      audit(user, 'knowledge.reindex');
      return { total: 0, embedded: 0, reused: 0, removed: 0, seconds: 0 }; // demo mode has no index to rebuild
    }],
  ];
}

export function customerAdminRoutes(asAdmin) {
  return [
    ['GET', /^\/admin\/customers$/, (_, __, user) => {
      asAdmin(user);
      const counts = {};
      for (const c of db.conversations.values()) counts[c.customer.id] = (counts[c.customer.id] ?? 0) + 1;
      return db.customers.map((c) => ({ ...c, conversations: counts[c.id] ?? 0, signedInOnce: true, lastSeenAt: null }));
    }],
    ['POST', /^\/admin\/customers\/([\w-]+)\/erase$/, ([id], body, user) => {
      asAdmin(user);
      if (body?.confirm !== id) throw new ApiError(400, "Confirm the erasure by sending the customer's id as `confirm`.");
      const index = db.customers.findIndex((c) => c.id === id);
      if (index < 0) throw new ApiError(404, `Customer ${id} not found.`);
      let removed = 0;
      for (const [cid, c] of db.conversations) {
        if (c.customer.id === id) {
          db.conversations.delete(cid);
          removed += 1;
        }
      }
      db.customers.splice(index, 1);
      for (const item of db.review.values()) item.conversationIds = item.conversationIds.filter((cid) => db.conversations.has(cid));
      audit(user, 'customer.erase', { customerId: id, detail: { conversations: removed, traces: 0, identityDeleted: false } });
      return { customerId: id, conversations: removed, traces: { deleted: 0 }, identity: { deleted: false, note: 'Demo mode has no Keycloak account to delete.' }, complete: true };
    }],
    ['GET', /^\/admin\/audit$/, (_, __, user, params = {}) => {
      asAdmin(user);
      return db.audit.filter((e) => (!params.action || e.action === params.action) && (!params.conversationId || e.conversationId === params.conversationId)).slice(0, Number(params.limit ?? 200));
    }],
  ];
}
