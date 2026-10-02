import { BOT_REPLY_KIND, CLOSED_REASON_META, SENDER, SYSTEM_EVENT } from '../../../constants/conversation.js';

// What a customer may see of their own conversation — the same rules as the real API
// (backend/app/conversation/views.py): transcript, cited articles, plain-language notes; no brief.

const firstName = (name) => (name ?? '').split(/\s+/)[0];

const EVENT_TEXT = {
  [SYSTEM_EVENT.HANDOFF_REQUESTED]: () => 'Connecting you with a member of our team…',
  [SYSTEM_EVENT.AGENT_JOINED]: (event) => `${firstName(event.agentName) || 'A support agent'} joined the chat`,
  [SYSTEM_EVENT.RETURNED_TO_BOT]: () => 'You’re chatting with the Baton assistant again',
  [SYSTEM_EVENT.RESOLVED]: (event) => CLOSED_REASON_META[event.closedReason]?.customerText ?? 'Conversation closed',
};

function customerMessage(message) {
  const base = { id: message.id, sender: message.sender, createdAt: message.createdAt };
  if (message.sender === SENDER.SYSTEM) {
    const text = EVENT_TEXT[message.event?.type]?.(message.event);
    return text ? { ...base, text } : null;
  }
  if (message.sender === SENDER.AGENT) return { ...base, text: message.text, author: { name: message.author?.name ?? 'Support' } };
  // One link per article: the bot often cites several chunks of the same page.
  const cited = message.meta?.kind === BOT_REPLY_KIND.ANSWER ? message.meta.sources : [];
  const sources = [...new Map(cited.map(({ title, url }) => [url, { title, url }])).values()];
  return { ...base, text: message.text, sources };
}

export const customerView = (conversation) => ({
  id: conversation.id,
  status: conversation.status,
  subject: conversation.subject,
  createdAt: conversation.createdAt,
  updatedAt: conversation.updatedAt,
  closedAt: conversation.closedAt ?? null,
  closedReason: conversation.closedReason ?? null,
  followUpOf: conversation.followUpOf ? { id: conversation.followUpOf.id, subject: conversation.followUpOf.subject } : null,
  agent: conversation.assignee ? { name: firstName(conversation.assignee.name) } : null,
  messages: conversation.messages.map(customerMessage).filter(Boolean),
});

export function customerSummary(conversation) {
  const last = conversation.messages.findLast((m) => m.sender !== SENDER.SYSTEM) ?? null;
  const { id, status, subject, createdAt, updatedAt } = conversation;
  return { id, status, subject, createdAt, updatedAt, closedReason: conversation.closedReason ?? null, lastMessage: last && { sender: last.sender, text: last.text, createdAt: last.createdAt } };
}
