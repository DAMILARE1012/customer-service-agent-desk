import { useState } from 'react';
import { Avatar, Badge, EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { CLOSED_REASON_META, STATUS_META } from '../../../constants/conversation.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';
import { errorMessage, formatRelative } from '../../../utils/format.js';
import { TranscriptDrawer } from '../../thread/components/TranscriptDrawer.jsx';
import { useGetAdminConversationsQuery, useGetAgentsQuery } from '../adminApi.js';
import { Card } from './Card.jsx';

const selectClass = 'rounded-lg border-0 bg-white py-1.5 pr-8 pl-3 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500';

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
                      <td className="px-5 py-3">
                        {c.closedReason ? (
                          <Badge tone={CLOSED_REASON_META[c.closedReason].tone}>{CLOSED_REASON_META[c.closedReason].label}</Badge>
                        ) : (
                          <Badge tone={STATUS_META[c.status].tone}>{STATUS_META[c.status].label}</Badge>
                        )}
                        {c.followUpOf && <span className="ml-1.5 text-[11px] text-indigo-600">follow-up</span>}
                      </td>
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
      {openId && <TranscriptDrawer conversationId={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
