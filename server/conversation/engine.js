import { propagateAttributes, startActiveObservation } from '@langfuse/tracing';
import * as core from '../../src/api/mock/engine/conversationEngine.js';
import { truncate } from '../../src/api/mock/engine/text.js';
import { CONVERSATION_STATUS, SENDER, SYSTEM_EVENT } from '../../src/constants/conversation.js';
import { HANDOFF_REASON } from '../../src/constants/handoff.js';
import { copilotDrafts, handoffs, handoffWait } from '../observability/metrics.js';
import { botTurn, draftCopilot } from './ragBot.js';

// Conversation lifecycle for the real backend. State transitions come from the shared engine
// (the same one the demo uses), so the handoff model is identical; bot turns and copilot drafts
// are async and LLM-backed. Every operation is one Langfuse trace, grouped by conversation as a
// session and by customer as a user.

export const { createConversation, returnToBot, resolveConversation } = core;

function traced(conversation, name, fn) {
  return propagateAttributes(
    {
      sessionId: conversation.id,
      userId: conversation.customer.id,
      traceName: name,
      tags: ['support-bot', `tier:${conversation.customer.tier}`],
      metadata: { customerTier: conversation.customer.tier },
    },
    () => startActiveObservation(name, fn),
  );
}

export function receiveCustomerMessage(conversation, text, now) {
  return traced(conversation, 'customer-message', async (span) => {
    span.update({ input: text });
    if (conversation.status === CONVERSATION_STATUS.RESOLVED) {
      conversation.status = CONVERSATION_STATUS.BOT_ACTIVE;
      conversation.assignee = null;
      core.addSystemEvent(conversation, SYSTEM_EVENT.REOPENED, 'Customer replied — conversation reopened', now);
    }

    const message = core.addMessage(conversation, { sender: SENDER.CUSTOMER, text, createdAt: now });
    conversation.subject ??= truncate(text, 70);
    const sentiment = core.trackSignals(conversation, message);

    let outcome = null;
    if (conversation.status === CONVERSATION_STATUS.BOT_ACTIVE) outcome = await botTurn(conversation, message, sentiment, now);
    else if (conversation.status === CONVERSATION_STATUS.AGENT_ACTIVE) conversation.copilot = await draftCopilot(conversation, text);
    // HANDOFF_PENDING: the bot has stepped aside and just listens.

    // What the trace list shows: the bot's reply, or why it stepped aside.
    const reply = outcome?.reply ?? (outcome?.kind === 'handed_off' ? `[handed off: ${outcome.reason}]` : `[${conversation.status}: bot not replying]`);
    span.update({ output: reply, metadata: { status: conversation.status, outcome: outcome?.kind ?? 'none' } });
    return conversation;
  });
}

export function acceptHandoff(conversation, agent, now) {
  return traced(conversation, 'accept-handoff', async () => {
    core.acceptHandoff(conversation, agent, now, { copilot: () => null });
    const { priority, requestedAt } = conversation.handoff;
    handoffWait.observe({ priority }, (now - requestedAt) / 1000);
    conversation.copilot = await draftCopilot(conversation, core.lastOpenQuestion(conversation));
    return conversation;
  });
}

export function takeOver(conversation, agent, now) {
  return traced(conversation, 'take-over', async () => {
    core.takeOver(conversation, agent, now, { copilot: () => null });
    handoffs.inc({ reason: HANDOFF_REASON.AGENT_INITIATED, priority: conversation.handoff.priority });
    conversation.copilot = await draftCopilot(conversation, core.lastOpenQuestion(conversation));
    return conversation;
  });
}

const words = (text) => new Set(text.toLowerCase().match(/[a-z0-9]+/g) ?? []);

/** What the agent did with the copilot draft: sent as-is, edited, or wrote their own. */
function classifyDraftUse(draft, sent) {
  if (draft.trim() === sent.trim()) return 'used';
  const a = words(draft);
  const b = words(sent);
  const overlap = [...a].filter((w) => b.has(w)).length / Math.max(1, new Set([...a, ...b]).size);
  return overlap >= 0.5 ? 'edited' : 'ignored';
}

export function postAgentMessage(conversation, agent, text, now) {
  if (conversation.copilot?.text && conversation.assignee?.id === agent.id) {
    copilotDrafts.inc({ action: classifyDraftUse(conversation.copilot.text, text) });
  }
  return core.postAgentMessage(conversation, agent, text, now);
}
