import { SENDER, SYSTEM_EVENT } from '../../../constants/conversation.js';
import { useAutoScroll } from '../../../hooks/useAutoScroll.js';

// What the customer sees for each lifecycle event (internal details stay internal).
const CUSTOMER_EVENT_TEXT = {
  [SYSTEM_EVENT.HANDOFF_REQUESTED]: () => 'Connecting you with a person…',
  [SYSTEM_EVENT.AGENT_JOINED]: (m) => m.text.split(' joined')[0] + ' joined the chat',
  [SYSTEM_EVENT.RETURNED_TO_BOT]: () => 'You’re chatting with the assistant again',
  [SYSTEM_EVENT.RESOLVED]: () => 'Conversation closed',
};

function CustomerViewMessage({ message }) {
  if (message.sender === SENDER.SYSTEM) {
    const text = CUSTOMER_EVENT_TEXT[message.event?.type]?.(message);
    return text ? <p className="py-1 text-center text-[11px] text-slate-400">{text}</p> : null;
  }

  const mine = message.sender === SENDER.CUSTOMER;
  const name = message.sender === SENDER.BOT ? 'Assistant' : message.author?.name;
  return (
    <div className={`flex flex-col ${mine ? 'items-end' : 'items-start'}`}>
      {!mine && <span className="mb-0.5 text-[10px] text-slate-400">{name}</span>}
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-1.5 text-sm ${
          mine ? 'rounded-br-sm bg-slate-900 text-white' : message.sender === SENDER.AGENT ? 'rounded-bl-sm bg-indigo-100 text-slate-800' : 'rounded-bl-sm bg-slate-100 text-slate-800'
        }`}
      >
        {message.text}
      </div>
    </div>
  );
}

/** The transcript from the customer's side of the widget. */
export function CustomerChatView({ messages }) {
  const ref = useAutoScroll(messages.length);
  return (
    <div ref={ref} className="min-h-0 flex-1 space-y-2 overflow-y-auto bg-white px-3 py-3">
      {messages.length === 0 && <p className="py-6 text-center text-xs text-slate-400">Say hi to start the conversation.</p>}
      {messages.map((message) => (
        <CustomerViewMessage key={message.id} message={message} />
      ))}
    </div>
  );
}
