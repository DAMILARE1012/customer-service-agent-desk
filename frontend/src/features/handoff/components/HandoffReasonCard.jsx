import { Icon } from '../../../components/ui/index.js';
import { PANEL_TONES, TEXT_TONES } from '../../../components/ui/tones.js';
import { HANDOFF_REASON_META, HANDOFF_STATUS } from '../../../constants/handoff.js';
import { formatClock, formatDuration } from '../../../utils/format.js';
import { PriorityBadge } from './PriorityBadge.jsx';
import { WaitTimer } from './WaitTimer.jsx';

function WaitLine({ handoff }) {
  if (handoff.status === HANDOFF_STATUS.PENDING) {
    return (
      <span className="flex items-center gap-1.5">
        Waiting <WaitTimer since={handoff.requestedAt} />
      </span>
    );
  }
  if (handoff.acceptedAt) {
    return (
      <span>
        Picked up by {handoff.acceptedBy?.name} after {formatDuration(handoff.acceptedAt - handoff.requestedAt)}
      </span>
    );
  }
  return null;
}

/** Why the bot stepped aside — primary reason, every signal that fired, and the SLA clock. */
export function HandoffReasonCard({ handoff }) {
  const meta = HANDOFF_REASON_META[handoff.reason];
  const otherSignals = handoff.signals.filter((s) => s.reason !== handoff.reason);

  return (
    <div className={`rounded-xl border p-3.5 ${PANEL_TONES[meta.tone]}`}>
      <div className="flex items-start justify-between gap-2">
        <p className={`flex items-center gap-2 text-sm font-semibold ${TEXT_TONES[meta.tone]}`}>
          <Icon name={meta.icon} className="size-5" />
          {meta.label}
        </p>
        <PriorityBadge priority={handoff.priority} />
      </div>
      <p className="mt-1.5 text-sm text-slate-700">{handoff.reasonDetail}</p>

      {otherSignals.length > 0 && (
        <ul className="mt-2 space-y-1">
          {otherSignals.map((signal) => (
            <li key={signal.reason} className="flex items-start gap-1.5 text-xs text-slate-600">
              <Icon name={HANDOFF_REASON_META[signal.reason].icon} className="mt-0.5 size-3.5 shrink-0" />
              <span>
                <span className="font-medium">Also: </span>
                {signal.detail}
              </span>
            </li>
          ))}
        </ul>
      )}

      {handoff.triggerMessage && (
        <blockquote className="mt-2.5 border-l-2 border-current/20 pl-2.5 text-xs text-slate-600 italic">“{handoff.triggerMessage.text}”</blockquote>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>Handed off at {formatClock(handoff.requestedAt)}</span>
        <WaitLine handoff={handoff} />
      </div>
    </div>
  );
}
