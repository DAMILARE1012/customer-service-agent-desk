import { useSelector } from 'react-redux';
import { selectCurrentAgent, useSetAvailabilityMutation } from '../../account/accountApi.js';
import { selectMyActiveCount } from '../../conversations/selectors.js';

/** Availability toggle (saved on the server: customers are told whether anyone is in) and load. */
export function AgentStatus() {
  const agent = useSelector(selectCurrentAgent);
  const [setAvailability, state] = useSetAvailabilityMutation();
  const active = useSelector(selectMyActiveCount);
  const online = agent.available !== false;

  if (agent.id && !agent.active) {
    return <span className="rounded-full bg-rose-500/15 px-2.5 py-1 text-[11px] font-medium text-rose-200 ring-1 ring-rose-400/30">Agent account disabled</span>;
  }

  return (
    <div className="hidden items-center gap-3 sm:flex">
      <span className="text-[11px] text-slate-400 tabular-nums">
        {active} / {agent.capacity || '—'} chats
      </span>
      <button
        type="button"
        onClick={() => setAvailability(!online)}
        disabled={state.isLoading || !agent.id}
        title={online ? 'Online — click to go away' : 'Away — click to go online'}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium text-slate-200 ring-1 ring-slate-600 transition hover:bg-white/10"
      >
        <span className={`size-2 rounded-full ${online ? 'bg-emerald-400' : 'bg-amber-400'}`} />
        {online ? 'Online' : 'Away'}
      </button>
    </div>
  );
}
