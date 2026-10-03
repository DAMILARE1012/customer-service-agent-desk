import { SENDER } from '../../../constants/conversation.js';

/**
 * Lightweight list shape for the queue — the full transcript is only sent for the open conversation.
 * Shared by the mock backend and the real one (server/api) so both return the same contract.
 */
export function toSummary(conversation) {
  const lastMessage = conversation.messages.findLast((m) => m.sender !== SENDER.SYSTEM) ?? null;
  const { id, customer, status, assignee, subject, createdAt, updatedAt, handoff, insights } = conversation;
  return {
    id,
    status,
    assignee,
    subject,
    createdAt,
    updatedAt,
    customer: { id: customer.id, name: customer.name, tier: customer.tier },
    lastMessage: lastMessage && { sender: lastMessage.sender, text: lastMessage.text, createdAt: lastMessage.createdAt },
    handoff: handoff && {
      reason: handoff.reason,
      priority: handoff.priority,
      requestedAt: handoff.requestedAt,
      acceptedAt: handoff.acceptedAt,
      addedWhileWaiting: handoff.addedWhileWaiting?.length ?? 0,
    },
    sentiment: insights.sentiment.current,
    lastConfidence: insights.lastConfidence,
    closedReason: conversation.closedReason ?? null,
    followUpOf: conversation.followUpOf?.id ?? null,
  };
}
