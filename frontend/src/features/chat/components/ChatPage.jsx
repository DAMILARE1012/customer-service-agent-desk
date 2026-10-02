import { useSelector } from 'react-redux';
import { navigate, pathSegments, usePath } from '../../../app/router.jsx';
import { selectUser } from '../../../auth/authSlice.js';
import { EmptyState, Spinner } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { POLLING_INTERVAL_MS } from '../../../constants/queue.js';
import { useAutoScroll } from '../../../hooks/useAutoScroll.js';
import { AppHeader } from '../../../layout/AppHeader.jsx';
import { errorMessage } from '../../../utils/format.js';
import { useGetMyConversationQuery, useGetMyConversationsQuery, useSendMessageMutation, useStartConversationMutation } from '../chatApi.js';
import { customerStatus } from '../chatStatus.js';
import { ChatComposer } from './ChatComposer.jsx';
import { ChatMessage, TypingIndicator } from './ChatMessage.jsx';
import { ChatWelcome } from './ChatWelcome.jsx';
import { ConversationSidebar } from './ConversationSidebar.jsx';

function Thread({ conversationId, onSend, sending }) {
  const { currentData: conversation, error, isLoading } = useGetMyConversationQuery(conversationId, { pollingInterval: POLLING_INTERVAL_MS });
  const messages = conversation?.messages ?? [];
  const botTyping = sending && conversation?.status === CONVERSATION_STATUS.BOT_ACTIVE;
  const scrollRef = useAutoScroll(messages.length + (botTyping ? 1 : 0));

  if (error) return <EmptyState icon="warning" title="Couldn’t open this conversation" description={errorMessage(error)} />;
  if (isLoading || !conversation) {
    return (
      <div className="flex flex-1 items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  const status = customerStatus(conversation);
  return (
    <>
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <p className="truncate text-sm font-semibold text-slate-900">{conversation.subject ?? 'New conversation'}</p>
        <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200">
          <span className={`size-1.5 rounded-full ${status.dot}`} />
          {status.label}
        </span>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 px-4 py-6">
          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}
          {botTyping && <TypingIndicator />}
        </div>
      </div>
      <div className="border-t border-slate-200 bg-slate-50/80 px-4 py-3">
        <div className="mx-auto w-full max-w-3xl">
          <ChatComposer onSend={onSend} sending={sending} placeholder={conversation.status === CONVERSATION_STATUS.RESOLVED ? 'Reply to reopen this conversation…' : 'Type a message…'} />
        </div>
      </div>
    </>
  );
}

/** The customer workspace: their conversations with Baton (and, after a handoff, a person). */
export function ChatPage() {
  const user = useSelector(selectUser);
  const [conversationId] = pathSegments(usePath(), '/chat');
  const { data: conversations = [], isLoading } = useGetMyConversationsQuery(undefined, { pollingInterval: POLLING_INTERVAL_MS * 3 });
  const [startConversation, startState] = useStartConversationMutation();
  const [sendMessage, sendState] = useSendMessageMutation();
  const sending = startState.isLoading || sendState.isLoading;

  const ask = async (text) => {
    let id = conversationId;
    if (!id) {
      id = (await startConversation().unwrap()).id;
      navigate(`/chat/${id}`);
    }
    sendMessage({ conversationId: id, text });
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50">
      <AppHeader tone="light" subtitle="Customer support" />
      <div className="flex min-h-0 flex-1">
        <ConversationSidebar conversations={conversations} isLoading={isLoading} selectedId={conversationId} onNew={() => navigate('/chat')} />
        <main className="flex min-w-0 flex-1 flex-col">
          {conversationId ? (
            <Thread key={conversationId} conversationId={conversationId} onSend={ask} sending={sending} />
          ) : (
            <ChatWelcome firstName={user.name.split(' ')[0]} onAsk={ask} sending={sending} />
          )}
          {(startState.error || sendState.error) && (
            <p className="bg-rose-50 px-4 py-2 text-center text-xs text-rose-700">{errorMessage(startState.error ?? sendState.error)}</p>
          )}
        </main>
      </div>
    </div>
  );
}
