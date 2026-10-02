import { useEffect } from 'react';
import { EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { CLOSED_REASON_META } from '../../../constants/conversation.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetConversationQuery } from '../../conversations/conversationsApi.js';
import { HandoffSummary } from '../../handoff/components/HandoffSummary.jsx';
import { MessageList } from './MessageList.jsx';

/** A conversation read-only, in a panel over the page: past sessions in the desk, any session in admin. */
export function TranscriptDrawer({ conversationId, onClose }) {
  const { currentData: conversation, error } = useGetConversationQuery(conversationId, { pollingInterval: 5000 });

  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const closed = conversation?.closedReason && CLOSED_REASON_META[conversation.closedReason];
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose} role="presentation">
      <aside className="flex h-full w-full max-w-2xl flex-col bg-slate-50 shadow-2xl" onClick={(e) => e.stopPropagation()} aria-label="Conversation transcript">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">{conversation?.customer.name ?? 'Conversation'}</p>
            <p className="truncate text-xs text-slate-500">
              {conversation?.subject}
              {closed && ` · ${closed.label}`}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <Icon name="x" className="size-5" />
          </button>
        </header>
        {error && <EmptyState icon="warning" title="Couldn’t load conversation" description={errorMessage(error)} />}
        {!conversation && !error && (
          <div className="flex flex-1 items-center justify-center text-slate-400">
            <Spinner />
          </div>
        )}
        {conversation && (
          <>
            {conversation.handoff && (
              <div className="border-b border-slate-200 bg-white">
                <HandoffSummary summary={conversation.handoff.summary} intent={conversation.handoff.intent} />
              </div>
            )}
            <MessageList messages={conversation.messages} customerName={conversation.customer.name} />
          </>
        )}
      </aside>
    </div>
  );
}
