import { Avatar } from '../../../components/ui/index.js';
import { SENDER } from '../../../constants/conversation.js';
import { formatClock } from '../../../utils/format.js';
import { BotReplyMeta } from './BotReplyMeta.jsx';

const STYLES = {
  [SENDER.CUSTOMER]: { row: 'justify-start', bubble: 'bg-white text-slate-800 ring-1 ring-slate-200 rounded-tl-sm' },
  [SENDER.BOT]: { row: 'justify-end', bubble: 'bg-sky-50 text-slate-800 ring-1 ring-sky-200 rounded-tr-sm' },
  [SENDER.AGENT]: { row: 'justify-end', bubble: 'bg-indigo-600 text-white rounded-tr-sm' },
};

function authorName(message, customerName) {
  if (message.sender === SENDER.CUSTOMER) return customerName;
  if (message.sender === SENDER.BOT) return 'Assistant';
  return message.author?.name ?? 'Agent';
}

export function MessageBubble({ message, customerName }) {
  const style = STYLES[message.sender];
  const fromCustomer = message.sender === SENDER.CUSTOMER;
  const name = authorName(message, customerName);

  const avatar = <Avatar name={name} kind={message.sender === SENDER.BOT ? 'bot' : 'person'} size="sm" />;

  return (
    <div className={`flex items-end gap-2 ${style.row}`}>
      {fromCustomer && avatar}
      <div className={`flex max-w-[72%] flex-col ${fromCustomer ? 'items-start' : 'items-end'}`}>
        <span className="mb-1 text-[11px] text-slate-400">
          {name} · {formatClock(message.createdAt)}
          {message.pending && ' · sending…'}
        </span>
        <div className={`rounded-2xl px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap ${style.bubble} ${message.pending ? 'opacity-60' : ''}`}>
          {message.text}
        </div>
        {message.sender === SENDER.BOT && <BotReplyMeta meta={message.meta} />}
      </div>
      {!fromCustomer && avatar}
    </div>
  );
}
