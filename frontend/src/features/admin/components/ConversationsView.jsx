import { useState } from 'react';
import { Avatar, Badge, EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { STATUS_META } from '../../../constants/conversation.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';
import { errorMessage, formatRelative } from '../../../utils/format.js';
import { useGetConversationQuery } from '../../conversations/conversationsApi.js';
import { HandoffSummary } from '../../handoff/components/HandoffSummary.jsx';
import { MessageList } from '../../thread/components/MessageList.jsx';
import { useGetAdminConversationsQuery, useGetAgentsQuery } from '../adminApi.js';
import { Card } from './Card.jsx';

const selectClass = 'rounded-lg border-0 bg-white py-1.5 pr-8 pl-3 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500';

/** Read-only transcript and brief, in a panel over the list. */
function ConversationDrawer({ id, onClose }) {
  const { currentData: conversation, error } = useGetConversationQuery(id, { pollingInterval: 5000 });
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose} role="presentation">
      <aside className="flex h-full w-full max-w-2xl flex-col bg-slate-50 shadow-2xl" onClick={(e) => e.stopPropagation()} aria-label="Conversation">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">{conversation?.customer.name ?? 'Conversation'}</p>
            <p className="truncate text-xs text-slate-500">{conversation?.subject}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label="Close">
            <Icon name="x" className="size-5" />
          </button>
        </header>
        {error && <EmptyState icon="warning" title="Couldn’t load conversation" description={errorMessage(error)} />}
        {!conversation && !error && <div className="flex flex-1 items-center justify-center text-slate-400"><Spinner /></div>}
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

export function ConversationsView() {
  const [filters, setFilters] = useState({ status: '', agentId: '', q: '' });
  const [openId, setOpenId] = useState(null);
  const { data: rows = [], error, isFetching } = useGetAdminConversationsQuery(filters, { pollingInterval: 10_000 });
  const { data: agents = [] } = useGetAgentsQuery();
  const set = (key) => (event) => setFilters((f) => ({ ...f, [key]: event.target.value }));

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <select value={filters.status} onChange={set('status')} className={selectClass} aria-label="Status">
          <option value="">All states</option>
          {Object.entries(STATUS_META).map(([status, meta]) => (
            <option key={status} value={status}>{meta.label}</option>
          ))}
        </select>
        <select value={filters.agentId} onChange={set('agentId')} className={selectClass} aria-label="Agent">
          <option value="">Any agent</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <label className="relative min-w-48 flex-1">
          <Icon name="search" className="pointer-events-none absolute top-2 left-2.5 size-4 text-slate-400" />
          <input value={filters.q} onChange={set('q')} placeholder="Customer or subject" className="w-full rounded-lg border-0 py-1.5 pr-3 pl-8 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500" />
        </label>
        {isFetching && <Spinner className="size-4 text-slate-400" />}
      </div>

      <Card>
        {error ? (
          <EmptyState icon="warning" title="Couldn’t load conversations" description={errorMessage(error)} />
        ) : rows.length === 0 ? (
          <EmptyState title="No conversations match" description="Try another state, agent or search." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-[11px] tracking-wider text-slate-500 uppercase">
                <tr className="border-b border-slate-100">
                  <th className="px-5 py-2.5 font-medium">Customer</th>
                  <th className="px-5 py-2.5 font-medium">State</th>
                  <th className="px-5 py-2.5 font-medium">Handoff</th>
                  <th className="px-5 py-2.5 font-medium">Agent</th>
                  <th className="px-5 py-2.5 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((c) => {
                  const reason = c.handoff && HANDOFF_REASON_META[c.handoff.reason];
                  return (
                    <tr key={c.id} onClick={() => setOpenId(c.id)} className="cursor-pointer hover:bg-slate-50">
                      <td className="max-w-80 px-5 py-3">
                        <div className="flex items-center gap-3">
                          <Avatar name={c.customer.name} size="sm" />
                          <div className="min-w-0">
                            <p className="font-medium text-slate-900">{c.customer.name}</p>
                            <p className="truncate text-xs text-slate-500">{c.subject ?? 'No messages yet'}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3"><Badge tone={STATUS_META[c.status].tone}>{STATUS_META[c.status].label}</Badge></td>
                      <td className="px-5 py-3 text-xs text-slate-600">{reason ? <span className="inline-flex items-center gap-1"><Icon name={reason.icon} className="size-3.5 text-slate-400" />{reason.label}</span> : '—'}</td>
                      <td className="px-5 py-3 text-xs text-slate-600">{c.assignee?.name ?? '—'}</td>
                      <td className="px-5 py-3 text-xs text-slate-500">{formatRelative(c.updatedAt)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {openId && <ConversationDrawer id={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
