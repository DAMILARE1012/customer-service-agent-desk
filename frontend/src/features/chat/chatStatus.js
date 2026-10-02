import { CLOSED_REASON, CONVERSATION_STATUS } from '../../constants/conversation.js';

// How each lifecycle state reads from the customer's side — no internal reasons, just who's helping.
export function customerStatus(conversation) {
  switch (conversation?.status) {
    case CONVERSATION_STATUS.HANDOFF_PENDING:
      return { label: 'Connecting you with our team', tone: 'amber', dot: 'bg-amber-500' };
    case CONVERSATION_STATUS.AGENT_ACTIVE:
      return { label: `Chatting with ${conversation.agent?.name ?? 'our team'}`, tone: 'indigo', dot: 'bg-indigo-500' };
    case CONVERSATION_STATUS.RESOLVED:
      return {
        label: conversation.closedReason === CLOSED_REASON.RESOLVED ? 'Resolved' : conversation.closedReason === CLOSED_REASON.ENDED_BY_CUSTOMER ? 'Ended' : 'Closed',
        tone: 'slate',
        dot: 'bg-slate-300',
      };
    default:
      return { label: 'Baton assistant', tone: 'sky', dot: 'bg-emerald-500' };
  }
}

export const isOpen = (conversation) => conversation.status !== CONVERSATION_STATUS.RESOLVED;

// Starter questions: two the help centre answers, and two that show the assistant stepping aside.
export const SUGGESTED_QUESTIONS = [
  'How do I connect a domain I bought elsewhere to my site?',
  'How long does a refund take to show up?',
  'There’s an unauthorized charge on my card',
  'Can I talk to a real person?',
];
