import { BatonMark } from '../../../components/brand/Brand.jsx';
import { Avatar, Icon, MessageText } from '../../../components/ui/index.js';
import { SENDER } from '../../../constants/conversation.js';
import { formatClock } from '../../../utils/format.js';

function Sources({ sources }) {
  if (!sources?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {sources.map((source) => (
        <a
          key={`${source.url}-${source.title}`}
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex max-w-full items-center gap-1 rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200 transition hover:text-indigo-600 hover:ring-indigo-200"
        >
          <Icon name="book" className="size-3.5 shrink-0" />
          <span className="truncate">{source.title}</span>
        </a>
      ))}
    </div>
  );
}

/** One message as the customer sees it. */
export function ChatMessage({ message }) {
  if (message.sender === SENDER.SYSTEM) {
    return (
      <div className="flex justify-center py-1">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-medium text-slate-500">{message.text}</span>
      </div>
    );
  }

  if (message.sender === SENDER.CUSTOMER) {
    return (
      <div className="flex flex-col items-end">
        <div className={`max-w-[80%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm text-white shadow-sm ${message.pending ? 'opacity-70' : ''}`}>
          {message.text}
        </div>
        <span className="mt-1 text-[10px] text-slate-400">{message.pending ? 'Sending…' : formatClock(message.createdAt)}</span>
      </div>
    );
  }

  const fromAgent = message.sender === SENDER.AGENT;
  return (
    <div className="flex items-start gap-2.5">
      {fromAgent ? <Avatar name={message.author?.name} size="sm" /> : <BatonMark className="size-7 shrink-0" />}
      <div className="min-w-0 max-w-[80%]">
        <p className="mb-1 flex items-center gap-1.5 text-[11px] text-slate-500">
          <span className="font-medium text-slate-700">{fromAgent ? message.author?.name : 'Baton assistant'}</span>
          {fromAgent && <span className="rounded bg-indigo-50 px-1.5 text-[10px] font-medium text-indigo-600">Support team</span>}
          <span>· {formatClock(message.createdAt)}</span>
        </p>
        <div className={`rounded-2xl rounded-tl-md px-4 py-2.5 text-sm whitespace-pre-line text-slate-800 shadow-sm ring-1 ${fromAgent ? 'bg-indigo-50 ring-indigo-100' : 'bg-white ring-slate-200'}`}>
          <MessageText text={message.text} />
        </div>
        <Sources sources={message.sources} />
      </div>
    </div>
  );
}

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-2.5" aria-live="polite">
      <BatonMark className="size-7 shrink-0" />
      <div className="flex items-center gap-1 rounded-2xl rounded-tl-md bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
        <span className="sr-only">The assistant is typing</span>
        {[0, 150, 300].map((delay) => (
          <span key={delay} className="size-1.5 animate-bounce rounded-full bg-slate-400" style={{ animationDelay: `${delay}ms` }} />
        ))}
      </div>
    </div>
  );
}
