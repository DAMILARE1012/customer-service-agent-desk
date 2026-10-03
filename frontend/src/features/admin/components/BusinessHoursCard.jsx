import { useEffect, useState } from 'react';
import { Button, Spinner } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetBusinessHoursQuery, useUpdateBusinessHoursMutation } from '../adminApi.js';
import { Card } from './Card.jsx';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** When the team is in. Outside these hours (or when no agent is online) customers are told when the
 * team is back and asked for an email, and the request waits in the queue instead of being dropped. */
export function BusinessHoursCard() {
  const { data, error, isLoading } = useGetBusinessHoursQuery(undefined, { pollingInterval: 30_000 });
  const [save, saveState] = useUpdateBusinessHoursMutation();
  const [draft, setDraft] = useState(null);

  useEffect(() => {
    if (data) setDraft(data.hours);
  }, [data]);

  if (isLoading || !draft) return <Card title="Business hours"><div className="flex justify-center py-8 text-slate-400"><Spinner /></div></Card>;
  if (error) return <Card title="Business hours"><p className="px-5 py-4 text-sm text-rose-700">{errorMessage(error)}</p></Card>;

  const set = (patch) => setDraft((d) => ({ ...d, ...patch }));
  const toggleDay = (day) => set({ days: draft.days.includes(day) ? draft.days.filter((d) => d !== day) : [...draft.days, day].sort() });
  const changed = JSON.stringify(draft) !== JSON.stringify(data.hours);
  const status = data.available
    ? `Customers can reach a person now · ${data.agentsOnline} agent${data.agentsOnline === 1 ? '' : 's'} online`
    : data.openNow
      ? 'Open, but no agent is online — customers are asked for an email'
      : `Closed${data.backAtText ? ` — back ${data.backAtText}` : ''}`;

  return (
    <Card title="Business hours" description={status}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save(draft);
        }}
        className="space-y-4 px-5 py-4"
      >
        <label className="flex items-center gap-2 text-sm text-slate-800">
          <input type="checkbox" checked={draft.enabled} onChange={(e) => set({ enabled: e.target.checked })} className="rounded text-indigo-600" />
          Only staffed during set hours (off = always staffed whenever an agent is online)
        </label>
        <fieldset disabled={!draft.enabled} className="grid gap-4 disabled:opacity-50 sm:grid-cols-2">
          <label className="text-xs text-slate-600">
            Time zone
            <input
              value={draft.timezone}
              onChange={(e) => set({ timezone: e.target.value })}
              placeholder="Africa/Lagos"
              className="mt-1 block w-full rounded-lg border-0 py-1.5 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500"
            />
          </label>
          <div className="flex gap-3">
            <label className="text-xs text-slate-600">
              Opens
              <input type="time" value={draft.open} onChange={(e) => set({ open: e.target.value })} className="mt-1 block rounded-lg border-0 py-1.5 text-sm ring-1 ring-slate-300" />
            </label>
            <label className="text-xs text-slate-600">
              Closes
              <input type="time" value={draft.close} onChange={(e) => set({ close: e.target.value })} className="mt-1 block rounded-lg border-0 py-1.5 text-sm ring-1 ring-slate-300" />
            </label>
          </div>
          <div className="sm:col-span-2">
            <p className="text-xs text-slate-600">Days</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {DAYS.map((name, day) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => toggleDay(day)}
                  aria-pressed={draft.days.includes(day)}
                  className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ${draft.days.includes(day) ? 'bg-indigo-600 text-white ring-indigo-600' : 'bg-white text-slate-600 ring-slate-300'}`}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
        </fieldset>
        {saveState.error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{errorMessage(saveState.error)}</p>}
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={!changed} loading={saveState.isLoading}>Save hours</Button>
          {saveState.isSuccess && !changed && <span className="text-sm text-emerald-700">Saved.</span>}
        </div>
      </form>
    </Card>
  );
}
