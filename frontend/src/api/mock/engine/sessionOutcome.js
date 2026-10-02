import { HANDOFF_REASON_META } from '../../../constants/handoff.js';

/**
 * One past session in a line or two — the agent's customer timeline and follow-up links. Same shape
 * as the API's (backend/app/conversation/views.py: session_outcome); built from what the session
 * recorded, no LLM call.
 */
export function sessionOutcome(conversation) {
  const packets = [...conversation.handoffHistory, ...(conversation.handoff ? [conversation.handoff] : [])];
  const last = packets.at(-1) ?? null;
  const answered = conversation.insights.attempts.filter((a) => a.outcome === 'answered').length;
  const summary = last
    ? last.summary
    : answered
      ? `The assistant answered ${answered} question${answered > 1 ? 's' : ''} without a handoff.`
      : conversation.subject
        ? 'The assistant didn’t reach an answer.'
        : 'No question was asked.';
  return {
    id: conversation.id,
    subject: conversation.subject,
    status: conversation.status,
    createdAt: conversation.createdAt,
    closedAt: conversation.closedAt ?? null,
    closedReason: conversation.closedReason ?? null,
    handoffReason: last?.reason ?? null,
    handoffLabel: last ? HANDOFF_REASON_META[last.reason]?.label ?? last.reason : null,
    handledBy: last?.acceptedBy?.name ?? null,
    botAnswers: answered,
    summary,
    followUpOf: conversation.followUpOf?.id ?? null,
  };
}
