import { useEffect, useState } from 'react';
import { Button, EmptyState, Spinner } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { useGetPolicyQuery, useResetPolicyMutation, useUpdatePolicyMutation } from '../adminApi.js';
import { Card } from './Card.jsx';

const LABELS = {
  noMatchThreshold: 'No-match threshold',
  sentimentThreshold: 'Frustration threshold',
  maxFailedAttempts: 'Failed attempts before handing off',
  procedureThreshold: 'Agent procedure match',
};

export function PolicyView() {
  const { data: policy, error, isLoading } = useGetPolicyQuery();
  const [updatePolicy, updateState] = useUpdatePolicyMutation();
  const [resetPolicy, resetState] = useResetPolicyMutation();
  const [draft, setDraft] = useState({});

  useEffect(() => {
    if (policy) setDraft(Object.fromEntries(Object.entries(policy.values).map(([k, v]) => [k, String(v)])));
  }, [policy]);

  if (isLoading) return <div className="flex justify-center py-16 text-slate-400"><Spinner /></div>;
  if (error) return <EmptyState icon="warning" title="Couldn’t load the policy" description={errorMessage(error)} />;

  const changed = Object.entries(draft).filter(([k, v]) => v !== '' && Number(v) !== policy.values[k]);
  const save = (event) => {
    event.preventDefault();
    updatePolicy(Object.fromEntries(changed.map(([k, v]) => [k, Number(v)])));
  };
  const mutationError = updateState.error ?? resetState.error;

  return (
    <form onSubmit={save} className="space-y-4">
      <Card
        title="Thresholds"
        description={policy.updatedBy ? `Last changed by ${policy.updatedBy} · ${new Date(policy.updatedAt).toLocaleString()}` : 'Using the defaults from .env'}
      >
        <div className="divide-y divide-slate-100">
          {Object.entries(policy.fields).map(([name, field]) => {
            const isDefault = policy.values[name] === policy.defaults[name];
            return (
              <div key={name} className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto] sm:items-center">
                <div>
                  <label htmlFor={`policy-${name}`} className="text-sm font-medium text-slate-900">
                    {LABELS[name] ?? name}
                  </label>
                  <p className="mt-0.5 text-xs text-slate-500">{field.help}</p>
                  <p className="mt-1 text-[11px] text-slate-400">
                    Default {policy.defaults[name]} · allowed {field.min} to {field.max}
                    {!isDefault && <span className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-700">changed</span>}
                  </p>
                </div>
                <input
                  id={`policy-${name}`}
                  type="number"
                  inputMode="decimal"
                  min={field.min}
                  max={field.max}
                  step={field.integer ? 1 : 0.01}
                  value={draft[name] ?? ''}
                  onChange={(e) => setDraft((d) => ({ ...d, [name]: e.target.value }))}
                  className="w-28 rounded-lg border-0 py-1.5 text-right text-sm tabular-nums ring-1 ring-slate-300 focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            );
          })}
        </div>
      </Card>

      {mutationError && <p className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{errorMessage(mutationError)}</p>}
      {updateState.isSuccess && !changed.length && <p className="text-sm text-emerald-700">Saved — the next customer message uses these values.</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!changed.length} loading={updateState.isLoading}>
          Save {changed.length ? `${changed.length} change${changed.length > 1 ? 's' : ''}` : ''}
        </Button>
        <Button variant="secondary" onClick={() => resetPolicy()} loading={resetState.isLoading}>
          Reset to defaults
        </Button>
        <p className="text-xs text-slate-500">Tip: calibrate the no-match threshold with <code className="rounded bg-slate-100 px-1">npm run eval</code> before changing it.</p>
      </div>
    </form>
  );
}
