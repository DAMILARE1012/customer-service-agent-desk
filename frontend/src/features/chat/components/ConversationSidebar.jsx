import { Link } from '../../../app/router.jsx';
import { Button, Spinner } from '../../../components/ui/index.js';
import { formatRelative } from '../../../utils/format.js';
import { customerStatus } from '../chatStatus.js';

/** The customer's own conversations, most recent first. */
export function ConversationSidebar({ conversations, isLoading, selectedId, onNew }) {
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <h2 className="text-xs font-semibold tracking-wider text-slate-500 uppercase">Your conversations</h2>
        <Button size="sm" variant="secondary" icon="plus" onClick={onNew}>
          New
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {isLoading && (
          <div className="flex justify-center py-6 text-slate-400">
            <Spinner />
          </div>
        )}
        {!isLoading && conversations.length === 0 && <p className="px-2 py-6 text-center text-xs text-slate-400">No conversations yet.</p>}
        <ul className="space-y-1">
          {conversations.map((conversation) => {
            const status = customerStatus(conversation);
            const active = conversation.id === selectedId;
            return (
              <li key={conversation.id}>
                <Link
                  to={`/chat/${conversation.id}`}
                  aria-current={active ? 'page' : undefined}
                  className={`block rounded-lg px-3 py-2.5 transition ${active ? 'bg-indigo-50 ring-1 ring-indigo-100' : 'hover:bg-slate-50'}`}
                >
                  <p className="truncate text-sm font-medium text-slate-800">{conversation.subject ?? 'New conversation'}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                    <span className={`size-1.5 rounded-full ${status.dot}`} />
                    <span className="truncate">{status.label}</span>
                    <span className="ml-auto shrink-0">{formatRelative(conversation.updatedAt)}</span>
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
