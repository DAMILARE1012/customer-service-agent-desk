import { useDispatch, useSelector } from 'react-redux';
import { Icon } from '../components/ui/index.js';
import { AgentStatus } from '../features/agent/components/AgentStatus.jsx';
import { selectSimulatorOpen, simulatorToggled } from '../features/simulator/simulatorSlice.js';
import { QueueStats } from './QueueStats.jsx';

export function TopBar() {
  const dispatch = useDispatch();
  const simulatorOpen = useSelector(selectSimulatorOpen);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-6 bg-slate-900 px-5">
      <div className="flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-indigo-500 text-white">
          <Icon name="chat" className="size-5" />
        </span>
        <div>
          <p className="text-sm font-semibold text-white">Handoff Desk</p>
          <p className="text-[11px] text-slate-400">RAG assistant · human handoff</p>
        </div>
      </div>

      <QueueStats />

      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => dispatch(simulatorToggled())}
          className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ring-1 transition ${
            simulatorOpen ? 'bg-white text-slate-900 ring-white' : 'text-slate-200 ring-slate-600 hover:bg-slate-800'
          }`}
        >
          <Icon name="user" className="size-4" />
          Customer simulator
        </button>
        <AgentStatus />
      </div>
    </header>
  );
}
