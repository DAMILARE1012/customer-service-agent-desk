import { useDispatch, useSelector } from 'react-redux';
import { Avatar } from '../../../components/ui/index.js';
import { selectMyActiveCount } from '../../conversations/selectors.js';
import { availabilityToggled, selectAvailability, selectCurrentAgent } from '../agentSlice.js';

export function AgentStatus() {
  const dispatch = useDispatch();
  const agent = useSelector(selectCurrentAgent);
  const availability = useSelector(selectAvailability);
  const active = useSelector(selectMyActiveCount);
  const online = availability === 'online';

  return (
    <div className="flex items-center gap-3">
      <div className="text-right">
        <p className="text-xs font-medium text-slate-200">{agent.name}</p>
        <p className="text-[11px] text-slate-400 tabular-nums">
          {active} / {agent.capacity} active chats
        </p>
      </div>
      <button
        type="button"
        onClick={() => dispatch(availabilityToggled())}
        className="relative"
        title={online ? 'Online — click to go away' : 'Away — click to go online'}
      >
        <Avatar name={agent.name} size="sm" />
        <span className={`absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-2 ring-slate-900 ${online ? 'bg-emerald-400' : 'bg-amber-400'}`} />
      </button>
    </div>
  );
}
