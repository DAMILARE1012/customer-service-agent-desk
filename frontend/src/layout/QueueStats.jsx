import { useSelector } from 'react-redux';
import { CONVERSATION_STATUS } from '../constants/conversation.js';
import { HANDOFF_SLA } from '../constants/handoff.js';
import { QUEUE_VIEW } from '../constants/queue.js';
import { selectAllConversations, selectQueueCounts } from '../features/conversations/selectors.js';
import { useNow } from '../hooks/useNow.js';
import { formatDuration } from '../utils/format.js';

function Stat({ label, value, tone = 'text-white' }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className={`text-sm font-semibold tabular-nums ${tone}`}>{value}</span>
      <span className="text-[11px] text-slate-400">{label}</span>
    </div>
  );
}

export function QueueStats() {
  const counts = useSelector(selectQueueCounts);
  const conversations = useSelector(selectAllConversations);
  const now = useNow(5000);

  const waits = conversations
    .filter((c) => c.status === CONVERSATION_STATUS.HANDOFF_PENDING)
    .map((c) => now - c.handoff.requestedAt);
  const longest = waits.length ? Math.max(...waits) : 0;
  const breaching = waits.filter((ms) => ms >= HANDOFF_SLA.breachAfterMs).length;

  return (
    <div className="hidden items-center gap-5 md:flex">
      <Stat label="waiting" value={counts[QUEUE_VIEW.NEEDS_AGENT] ?? 0} tone="text-amber-300" />
      <Stat label="longest wait" value={waits.length ? formatDuration(longest) : '—'} />
      <Stat label="over SLA" value={breaching} tone={breaching ? 'text-rose-300' : 'text-white'} />
      <Stat label="bot live" value={counts[QUEUE_VIEW.BOT_LIVE] ?? 0} tone="text-sky-300" />
    </div>
  );
}
