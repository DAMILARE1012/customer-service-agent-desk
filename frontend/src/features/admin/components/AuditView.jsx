import { useState } from 'react';
import { EmptyState, Spinner } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { TranscriptDrawer } from '../../thread/components/TranscriptDrawer.jsx';
import { useGetAuditQuery } from '../adminApi.js';
import { Card } from './Card.jsx';

const ACTIONS = {
  'conversation.view': 'Opened a transcript',
  'customer.timeline.view': 'Opened a customer’s history',
  'customer.erase': 'Deleted a customer’s data',
  'agent.update': 'Changed an agent',
  'policy.update': 'Changed the handoff policy',
  'policy.reset': 'Reset the handoff policy',
  'review.run': 'Ran the review',
  'review.publish': 'Published an article',
  'review.approve': 'Approved a test question',
  'review.reject': 'Dismissed a review item',
  'knowledge.reindex': 'Indexed the help centre',
};

function detailText(entry) {
  const d = entry.detail ?? {};
  if (entry.action === 'customer.erase') return `${d.conversations} conversations, ${d.traces} traces, account ${d.identityDeleted ? 'deleted' : 'not deleted'}`;
  if (entry.action === 'agent.update') return Object.entries(d).filter(([k]) => k !== 'agentId').map(([k, v]) => `${k} → ${v}`).join(', ') + ` (${d.agentId})`;
  if (entry.action === 'policy.update') return Object.entries(d).map(([k, v]) => `${k} → ${v}`).join(', ');
  if (entry.action === 'review.publish') return d.path;
  return '';
}

export function AuditView() {
  const [action, setAction] = useState('');
  const { data: entries = [], error, isLoading } = useGetAuditQuery({ action, limit: 300 }, { pollingInterval: 15_000 });
  const [openId, setOpenId] = useState(null);

  if (isLoading) return <div className="flex justify-center py-16 text-slate-400"><Spinner /></div>;
  if (error) return <EmptyState icon="warning" title="Couldn’t load the audit log" description={errorMessage(error)} />;

  return (
    <>
      <select value={action} onChange={(e) => setAction(e.target.value)} className="rounded-lg border-0 py-1.5 pr-8 pl-3 text-sm ring-1 ring-slate-300" aria-label="Action">
        <option value="">Everything</option>
        {Object.entries(ACTIONS).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select>
      <Card title="Who accessed what" description="Transcript views are recorded once per person per conversation every 10 minutes. Kept for audit; contains no message text.">
        {entries.length === 0 ? (
          <EmptyState icon="shield" title="Nothing recorded yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-[11px] tracking-wider text-slate-500 uppercase">
                <tr className="border-b border-slate-100">
                  <th className="px-5 py-2.5 font-medium">When</th>
                  <th className="px-5 py-2.5 font-medium">Who</th>
                  <th className="px-5 py-2.5 font-medium">What</th>
                  <th className="px-5 py-2.5 font-medium">Subject</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {entries.map((e) => (
                  <tr key={e.id}>
                    <td className="px-5 py-2.5 text-xs whitespace-nowrap text-slate-500">{new Date(e.at).toLocaleString()}</td>
                    <td className="px-5 py-2.5">
                      <span className="font-medium text-slate-800">{e.actorName ?? '—'}</span>
                      <span className="ml-1.5 text-[11px] text-slate-400">{e.actorRole}</span>
                    </td>
                    <td className="px-5 py-2.5 text-slate-700">
                      {ACTIONS[e.action] ?? e.action}
                      {detailText(e) && <span className="ml-1.5 text-xs text-slate-500">· {detailText(e)}</span>}
                    </td>
                    <td className="px-5 py-2.5 text-xs">
                      {e.conversationId ? (
                        <button type="button" onClick={() => setOpenId(e.conversationId)} className="text-indigo-600 hover:text-indigo-500">{e.conversationId}</button>
                      ) : (
                        <span className="text-slate-500">{e.customerId ?? ''}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {openId && <TranscriptDrawer conversationId={openId} onClose={() => setOpenId(null)} />}
    </>
  );
}
