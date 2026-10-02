import { CONVERSATION_STATUS } from '../../constants/conversation.js';

// How each lifecycle state reads from the customer's side — no internal reasons, just who's helping.
export function customerStatus(conversation) {
  switch (conversation?.status) {
    case CONVERSATION_STATUS.HANDOFF_PENDING:
      return { label: 'Connecting you with our team', tone: 'amber', dot: 'bg-amber-500' };
    case CONVERSATION_STATUS.AGENT_ACTIVE:
      return { label: `Chatting with ${conversation.agent?.name ?? 'our team'}`, tone: 'indigo', dot: 'bg-indigo-500' };
    case CONVERSATION_STATUS.RESOLVED:
      return { label: 'Closed', tone: 'slate', dot: 'bg-slate-400' };
    default:
      return { label: 'Baton assistant', tone: 'sky', dot: 'bg-emerald-500' };
  }
}

// Starter questions: two the help centre answers, and two that show the assistant stepping aside.
export const SUGGESTED_QUESTIONS = [
  'How do I connect a domain I bought elsewhere to my site?',
  'How long does a refund take to show up?',
  'There’s an unauthorized charge on my card',
  'Can I talk to a real person?',
];
