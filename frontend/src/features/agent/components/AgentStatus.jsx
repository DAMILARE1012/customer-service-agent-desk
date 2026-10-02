import { useDispatch, useSelector } from 'react-redux';
import { selectCurrentAgent } from '../../account/accountApi.js';
import { selectMyActiveCount } from '../../conversations/selectors.js';
import { availabilityToggled, selectAvailability } from '../agentSlice.js';

/** Availability toggle and load (active chats / capacity set by an admin). */
export function AgentStatus() {
  const dispatch = useDispatch();
  const agent = useSelector(selectCurrentAgent);
  const availability = useSelector(selectAvailability);
  const active = useSelector(selectMyActiveCount);
  const online = availability === 'online';

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
        onClick={() => dispatch(availabilityToggled())}
        title={online ? 'Online — click to go away' : 'Away — click to go online'}
        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium text-slate-200 ring-1 ring-slate-600 transition hover:bg-white/10"
      >
        <span className={`size-2 rounded-full ${online ? 'bg-emerald-400' : 'bg-amber-400'}`} />
        {online ? 'Online' : 'Away'}
      </button>
    </div>
  );
}
