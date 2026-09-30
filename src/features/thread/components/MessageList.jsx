import { SENDER } from '../../../constants/conversation.js';
import { useAutoScroll } from '../../../hooks/useAutoScroll.js';
import { MessageBubble } from './MessageBubble.jsx';
import { SystemEvent } from './SystemEvent.jsx';

export function MessageList({ messages, customerName }) {
  const scrollRef = useAutoScroll(messages.length);

  return (
    <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
      {messages.map((message) =>
        message.sender === SENDER.SYSTEM ? (
          <SystemEvent key={message.id} message={message} />
        ) : (
          <MessageBubble key={message.id} message={message} customerName={customerName} />
        ),
      )}
    </div>
  );
}
