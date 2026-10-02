import { Avatar, Badge, EmptyState, Icon, Spinner } from '../../../components/ui/index.js';
import { errorMessage, formatRelative } from '../../../utils/format.js';
import { useGetAgentsQuery, useGetInsightsQuery, useUpdateAgentMutation } from '../adminApi.js';
import { Card } from './Card.jsx';

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition ${checked ? 'bg-emerald-500' : 'bg-slate-300'}`}
    >
      <span className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition ${checked ? 'left-[18px]' : 'left-0.5'}`} />
    </button>
  );
}

function CapacityStepper({ value, onChange }) {
  const button = 'flex size-7 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 disabled:opacity-30';
  return (
    <div className="inline-flex items-center gap-1 rounded-lg ring-1 ring-slate-200">
      <button type="button" className={button} disabled={value <= 1} onClick={() => onChange(value - 1)} aria-label="Lower capacity">−</button>
      <span className="w-6 text-center text-sm font-medium tabular-nums">{value}</span>
      <button type="button" className={button} disabled={value >= 20} onClick={() => onChange(value + 1)} aria-label="Raise capacity">+</button>
    </div>
  );
}

export function AgentsView() {
  const { data: agents = [], error, isLoading } = useGetAgentsQuery(undefined, { pollingInterval: 10_000 });
  const { data: insights } = useGetInsightsQuery();
  const [updateAgent, { error: updateError }] = useUpdateAgentMutation();

  if (isLoading) return <div className="flex justify-center py-16 text-slate-400"><Spinner /></div>;
  if (error) return <EmptyState icon="warning" title="Couldn’t load agents" description={errorMessage(error)} />;

  const invite = insights?.links?.keycloakUsers;
  return (
    <Card
      title={`${agents.length} agents`}
      description="Capacity caps how many conversations an agent can hold at once; a disabled agent can’t use the desk."
      aside={
        invite && (
          <a href={invite} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-500">
            Invite in Keycloak <Icon name="external" className="size-3.5" />
          </a>
        )
      }
    >
      {updateError && <p className="bg-rose-50 px-5 py-2 text-xs text-rose-700">{errorMessage(updateError)}</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-[11px] tracking-wider text-slate-500 uppercase">
            <tr className="border-b border-slate-100">
              <th className="px-5 py-2.5 font-medium">Agent</th>
              <th className="px-5 py-2.5 font-medium">Active chats</th>
              <th className="px-5 py-2.5 font-medium">Capacity</th>
              <th className="px-5 py-2.5 font-medium">Last seen</th>
              <th className="px-5 py-2.5 font-medium">Enabled</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {agents.map((agent) => (
              <tr key={agent.id} className={agent.active ? '' : 'bg-slate-50/70'}>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <Avatar name={agent.name} size="sm" />
                    <div className="min-w-0">
                      <p className="font-medium text-slate-900">{agent.name}</p>
                      <p className="truncate text-xs text-slate-500">{agent.email}</p>
                    </div>
                    {!agent.signedInOnce && <Badge tone="amber">Hasn’t signed in yet</Badge>}
                  </div>
                </td>
                <td className="px-5 py-3 text-slate-700 tabular-nums">
                  {agent.activeChats}
                  <span className="text-slate-400"> / {agent.capacity}</span>
                </td>
                <td className="px-5 py-3">
                  <CapacityStepper value={agent.capacity} onChange={(capacity) => updateAgent({ id: agent.id, capacity })} />
                </td>
                <td className="px-5 py-3 text-xs text-slate-500">{agent.lastSeenAt ? formatRelative(new Date(agent.lastSeenAt).getTime()) : '—'}</td>
                <td className="px-5 py-3">
                  <Toggle checked={agent.active} label={`${agent.active ? 'Disable' : 'Enable'} ${agent.name}`} onChange={(active) => updateAgent({ id: agent.id, active })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
