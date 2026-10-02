import { useState } from 'react';
import { BatonMark } from '../../../components/brand/Brand.jsx';
import { Button, Icon, Spinner } from '../../../components/ui/index.js';
import { CLOSED_REASON_META, CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { POLLING_INTERVAL_MS } from '../../../constants/queue.js';
import { useAutoScroll } from '../../../hooks/useAutoScroll.js';
import { errorMessage, formatRelative } from '../../../utils/format.js';
import {
  useEndConversationMutation,
  useGetMyConversationQuery,
  useGetMyConversationsQuery,
  useSendMessageMutation,
  useStartConversationMutation,
} from '../../chat/chatApi.js';
import { SUGGESTED_QUESTIONS, customerStatus, isOpen } from '../../chat/chatStatus.js';
import { ChatComposer } from '../../chat/components/ChatComposer.jsx';
import { ChatMessage, TypingIndicator } from '../../chat/components/ChatMessage.jsx';
import { PrivacyNotice } from '../../chat/components/PrivacyNotice.jsx';

function Welcome({ name, onAsk, sending }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5">
      <div className="space-y-1">
        <p className="text-lg font-semibold text-slate-900">Hi{name ? ` ${name}` : ''}, how can we help?</p>
        <p className="text-sm text-slate-600">Ask us anything. The assistant answers from our help centre, and brings in a person when it can’t help — they’ll see everything you’ve said.</p>
      </div>
      <div className="mt-4 space-y-2">
        {SUGGESTED_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            disabled={sending}
            onClick={() => onAsk(q)}
            className="flex w-full items-start gap-2 rounded-xl bg-white px-3 py-2.5 text-left text-sm text-slate-700 ring-1 ring-slate-200 transition hover:text-indigo-700 hover:ring-indigo-300 disabled:opacity-50"
          >
            <Icon name="chat" className="mt-0.5 size-4 shrink-0 text-slate-400" />
            {q}
          </button>
        ))}
      </div>
      <PrivacyNotice className="mt-auto pt-5" />
    </div>
  );
}

function History({ conversations, onPick, onNew, canStartNew }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      {canStartNew && (
        <Button size="sm" icon="plus" className="mb-3 w-full" onClick={onNew}>
          New conversation
        </Button>
      )}
      <ul className="space-y-1.5">
        {conversations.map((c) => {
          const status = customerStatus(c);
          return (
            <li key={c.id}>
              <button type="button" onClick={() => onPick(c.id)} className="w-full rounded-lg px-3 py-2.5 text-left ring-1 ring-slate-200 hover:bg-slate-50">
                <p className="truncate text-sm font-medium text-slate-800">{c.subject ?? 'New conversation'}</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                  <span className={`size-1.5 rounded-full ${status.dot}`} />
                  {status.label}
                  <span className="ml-auto">{formatRelative(c.updatedAt)}</span>
                </p>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Thread({ conversationId, onSend, sending, onStart, starting }) {
  const { currentData: conversation } = useGetMyConversationQuery(conversationId);
  const open = conversation ? isOpen(conversation) : false;
  useGetMyConversationQuery(conversationId, { pollingInterval: POLLING_INTERVAL_MS, skip: !open });
  const [endConversation, endState] = useEndConversationMutation();
  const messages = conversation?.messages ?? [];
  const botTyping = sending && conversation?.status === CONVERSATION_STATUS.BOT_ACTIVE;
  const scrollRef = useAutoScroll(messages.length + (botTyping ? 1 : 0));

  if (!conversation) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }
  return (
    <>
      {(conversation.followUpOf || open) && (
        <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-1.5 text-[11px] text-slate-500">
          <span className="truncate">{conversation.followUpOf ? `Following up on “${conversation.followUpOf.subject ?? 'an earlier chat'}”` : 'Conversation in progress'}</span>
          {open && (
            <button type="button" onClick={() => endConversation(conversationId)} disabled={endState.isLoading} className="shrink-0 font-medium text-slate-500 hover:text-rose-600">
              End chat
            </button>
          )}
        </div>
      )}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-4">
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        {botTyping && <TypingIndicator />}
      </div>
      <div className="border-t border-slate-200 bg-white p-2.5">
        {open ? (
          <ChatComposer onSend={onSend} sending={sending} placeholder="Write a message…" />
        ) : (
          <div className="space-y-2 px-1 py-1 text-center">
            <p className="text-xs text-slate-600">{CLOSED_REASON_META[conversation.closedReason]?.customerText ?? 'This conversation has ended.'}</p>
            <div className="flex justify-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => onStart()} disabled={starting}>New chat</Button>
              <Button size="sm" icon="refresh" onClick={() => onStart(conversation.id)} loading={starting}>Follow up on this</Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

/** The chat panel the launcher opens: welcome, the live conversation, or past ones (read-only). */
export function WidgetPanel({ session, error, onRetry, onClose }) {
  const [view, setView] = useState('chat'); // chat | history
  const [pickedId, setPickedId] = useState(null);
  const { data: conversations = [] } = useGetMyConversationsQuery(undefined, { skip: !session, pollingInterval: POLLING_INTERVAL_MS * 3 });
  const [startConversation, startState] = useStartConversationMutation();
  const [sendMessage, sendState] = useSendMessageMutation();
  const live = conversations.find(isOpen);
  const currentId = pickedId ?? live?.id ?? null;
  const current = conversations.find((c) => c.id === currentId);
  const firstName = session?.customer?.name?.startsWith('Visitor') ? null : session?.customer?.name?.split(' ')[0];

  const start = async (followUpOf) => {
    const created = await startConversation(followUpOf ? { followUpOf } : {}).unwrap();
    setPickedId(created.id);
    setView('chat');
    return created.id;
  };
  const ask = async (text) => sendMessage({ conversationId: currentId && current && isOpen(current) ? currentId : await start(), text });

  return (
    <section className="flex h-full w-full flex-col overflow-hidden rounded-2xl bg-slate-50 shadow-[0_2px_6px_rgba(15,23,42,0.18)] ring-1 ring-slate-900/10" aria-label="Support chat">
      <header className="flex items-center gap-3 bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-white">
        {view === 'history' ? (
          <button type="button" onClick={() => setView('chat')} className="rounded p-1 hover:bg-white/15" aria-label="Back to the conversation">
            <Icon name="returnLeft" className="size-5" />
          </button>
        ) : (
          <BatonMark className="size-8 rounded-lg ring-1 ring-white/30" />
        )}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{view === 'history' ? 'Your conversations' : 'Support'}</p>
          <p className="truncate text-[11px] text-indigo-100">{view === 'history' ? `${conversations.length} in total` : current ? customerStatus(current).label : 'Usually answers in seconds'}</p>
        </div>
        {view === 'chat' && conversations.length > 0 && (
          <button type="button" onClick={() => setView('history')} className="rounded p-1.5 hover:bg-white/15" aria-label="Your conversations" title="Your conversations">
            <Icon name="clock" className="size-5" />
          </button>
        )}
        <button type="button" onClick={onClose} className="rounded p-1.5 hover:bg-white/15" aria-label="Minimise chat" title="Minimise">
          <Icon name="chevronDown" className="size-5" />
        </button>
      </header>

      {error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
          <Icon name="warning" className="size-6 text-amber-500" />
          <p className="text-sm text-slate-600">{error}</p>
          <Button size="sm" variant="secondary" onClick={onRetry}>Try again</Button>
        </div>
      ) : !session ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-400">
          <Spinner className="size-4" /> Starting chat…
        </div>
      ) : view === 'history' ? (
        <History conversations={conversations} canStartNew={!live} onNew={() => { setPickedId(null); setView('chat'); }} onPick={(id) => { setPickedId(id); setView('chat'); }} />
      ) : currentId ? (
        <Thread key={currentId} conversationId={currentId} onSend={ask} sending={sendState.isLoading} onStart={start} starting={startState.isLoading} />
      ) : (
        <Welcome name={firstName} onAsk={ask} sending={startState.isLoading || sendState.isLoading} />
      )}
      {(startState.error || sendState.error) && <p className="bg-rose-50 px-3 py-1.5 text-center text-[11px] text-rose-700">{errorMessage(startState.error ?? sendState.error)}</p>}
    </section>
  );
}
