import { Icon } from '../../../components/ui/index.js';
import { HANDOFF_SLA } from '../../../constants/handoff.js';
import { useNow } from '../../../hooks/useNow.js';
import { formatDuration } from '../../../utils/format.js';

const slaTone = (ms) =>
  ms >= HANDOFF_SLA.breachAfterMs ? 'text-rose-600' : ms >= HANDOFF_SLA.warnAfterMs ? 'text-amber-600' : 'text-slate-500';

/** Live "waiting for an agent" timer, coloured against the handoff SLA. */
export function WaitTimer({ since }) {
  const now = useNow(1000);
  const waited = now - since;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium tabular-nums ${slaTone(waited)}`} title="Time waiting for an agent">
      <Icon name="clock" className="size-3.5" />
      {formatDuration(waited)}
    </span>
  );
}
