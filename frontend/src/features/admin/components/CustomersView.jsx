import { useState } from 'react';
import { Avatar, Badge, Button, EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { CUSTOMER_TIER_META } from '../../../constants/conversation.js';
import { errorMessage, formatRelative } from '../../../utils/format.js';
import { useEraseCustomerMutation, useGetCustomersAdminQuery } from '../adminApi.js';
import { Card } from './Card.jsx';

/** Irreversible: the admin types the customer's name to confirm, then sees exactly what was removed. */
function EraseDialog({ customer, onClose }) {
  const [typed, setTyped] = useState('');
  const [erase, { data: report, isLoading, error }] = useEraseCustomerMutation();
  const confirmed = typed.trim().toLowerCase() === customer.name.toLowerCase();

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true" aria-label="Delete customer data">
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl">
        {!report ? (
          <>
            <div className="flex items-start gap-3">
              <span className="rounded-full bg-rose-100 p-2 text-rose-600">
                <Icon name="trash" className="size-5" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Delete all data for {customer.name}?</h2>
                <p className="mt-1 text-sm text-slate-600">
                  This permanently deletes their profile and all {customer.conversations} conversation{customer.conversations === 1 ? '' : 's'} with every message and
                  handoff brief, and their Langfuse traces. Their chat widget session stops working. It can’t be undone.
                </p>
              </div>
            </div>
            <label className="mt-4 block text-xs font-medium text-slate-600">
              Type <span className="font-semibold text-slate-900">{customer.name}</span> to confirm
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus className="mt-1 w-full rounded-lg border-0 py-2 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-rose-500" />
            </label>
            {error && <p className="mt-2 text-xs text-rose-700">{errorMessage(error)}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>Cancel</Button>
              <Button variant="danger" disabled={!confirmed} loading={isLoading} onClick={() => erase(customer.id)}>
                Delete everything
              </Button>
            </div>
          </>
        ) : (
          <>
            <h2 className="text-base font-semibold text-slate-900">{report.complete ? 'Customer data deleted' : 'Deleted — with something left to do'}</h2>
            <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
              <li className="flex gap-2"><Icon name="checkCircle" className="size-4 text-emerald-600" /> Profile and {report.conversations} conversation{report.conversations === 1 ? '' : 's'}</li>
              <li className="flex gap-2">
                <Icon name={report.traces.error ? 'warning' : 'checkCircle'} className={`size-4 ${report.traces.error ? 'text-amber-600' : 'text-emerald-600'}`} />
                {report.traces.error ?? `${report.traces.deleted} Langfuse trace${report.traces.deleted === 1 ? '' : 's'}`}
              </li>
              <li className="flex gap-2">
                <Icon name={report.identity.deleted ? 'checkCircle' : 'warning'} className={`size-4 ${report.identity.deleted ? 'text-emerald-600' : 'text-amber-600'}`} />
                {report.identity.deleted ? 'Sign-in account' : report.identity.note}
              </li>
            </ul>
            <p className="mt-3 text-xs text-slate-500">Recorded in the audit log (counts only, no personal data).</p>
            <div className="mt-4 flex justify-end">
              <Button onClick={onClose}>Done</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function CustomersView() {
  const { data: customers = [], error, isLoading } = useGetCustomersAdminQuery();
  const [term, setTerm] = useState('');
  const [erasing, setErasing] = useState(null);

  if (isLoading) return <div className="flex justify-center py-16 text-slate-400"><Spinner /></div>;
  if (error) return <EmptyState icon="warning" title="Couldn’t load customers" description={errorMessage(error)} />;

  const query = term.trim().toLowerCase();
  const rows = customers.filter((c) => !query || c.name.toLowerCase().includes(query) || (c.email ?? '').toLowerCase().includes(query));
  return (
    <>
      <label className="relative block max-w-sm">
        <Icon name="search" className="pointer-events-none absolute top-2 left-2.5 size-4 text-slate-400" />
        <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Name or email" className="w-full rounded-lg border-0 py-1.5 pr-3 pl-8 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500" />
      </label>
      <Card title={`${customers.length} customers`} description="A customer’s right to be forgotten: one step deletes everything Baton holds about them.">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-[11px] tracking-wider text-slate-500 uppercase">
              <tr className="border-b border-slate-100">
                <th className="px-5 py-2.5 font-medium">Customer</th>
                <th className="px-5 py-2.5 font-medium">Tier</th>
                <th className="px-5 py-2.5 font-medium">Conversations</th>
                <th className="px-5 py-2.5 font-medium">Last seen</th>
                <th className="px-5 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((c) => (
                <tr key={c.id}>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <Avatar name={c.name} size="sm" />
                      <div className="min-w-0">
                        <p className="font-medium text-slate-900">
                          {c.name}
                          {c.isVisitor && <span className="ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500">website visitor</span>}
                        </p>
                        <p className="truncate text-xs text-slate-500">{c.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3"><Badge tone={CUSTOMER_TIER_META[c.tier]?.tone ?? 'slate'}>{CUSTOMER_TIER_META[c.tier]?.label ?? c.tier}</Badge></td>
                  <td className="px-5 py-3 text-slate-700 tabular-nums">{c.conversations}</td>
                  <td className="px-5 py-3 text-xs text-slate-500">{c.lastSeenAt ? formatRelative(new Date(c.lastSeenAt).getTime()) : '—'}</td>
                  <td className="px-5 py-3 text-right">
                    <Button variant="dangerGhost" size="sm" icon="trash" onClick={() => setErasing(c)}>
                      Delete data
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {erasing && <EraseDialog customer={erasing} onClose={() => setErasing(null)} />}
    </>
  );
}
