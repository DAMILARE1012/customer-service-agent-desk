import { useDispatch } from 'react-redux';
import { Icon } from '../../../components/ui/index.js';
import { SYSTEM_EVENT } from '../../../constants/conversation.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';
import { formatClock } from '../../../utils/format.js';
import { contextTabChanged } from '../../conversations/deskSlice.js';

const EVENT_STYLE = {
  [SYSTEM_EVENT.HANDOFF_REQUESTED]: { icon: 'arrowRight', className: 'bg-amber-50 text-amber-800 ring-amber-200' },
  [SYSTEM_EVENT.AGENT_JOINED]: { icon: 'user', className: 'bg-indigo-50 text-indigo-700 ring-indigo-200' },
  [SYSTEM_EVENT.AGENT_TOOK_OVER]: { icon: 'arrowRight', className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  [SYSTEM_EVENT.RETURNED_TO_BOT]: { icon: 'returnLeft', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  [SYSTEM_EVENT.RESOLVED]: { icon: 'checkCircle', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  [SYSTEM_EVENT.REOPENED]: { icon: 'refresh', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
  [SYSTEM_EVENT.PRIORITY_RAISED]: { icon: 'warning', className: 'bg-rose-50 text-rose-700 ring-rose-200' },
  [SYSTEM_EVENT.CONTACT_LEFT]: { icon: 'mail', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  [SYSTEM_EVENT.CUSTOMER_LEFT]: { icon: 'logout', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
  [SYSTEM_EVENT.CUSTOMER_RETURNED]: { icon: 'user', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
};

/** Lifecycle markers in the transcript. Handoffs are events in the story, not errors. */
export function SystemEvent({ message }) {
  const dispatch = useDispatch();
  const abandoned = message.event?.closedReason === 'abandoned';
  const style = abandoned
    ? { icon: 'warning', className: 'bg-amber-50 text-amber-800 ring-amber-200' }
    : (EVENT_STYLE[message.event?.type] ?? EVENT_STYLE[SYSTEM_EVENT.REOPENED]);
  const isHandoff = message.event?.type === SYSTEM_EVENT.HANDOFF_REQUESTED;
  const reasonIcon = isHandoff ? HANDOFF_REASON_META[message.event.reason]?.icon : style.icon;

  return (
    <div className="flex items-center gap-3 py-1" role="status">
      <span className="h-px flex-1 bg-slate-200" />
      <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${style.className}`}>
        <Icon name={reasonIcon} className="size-3.5" />
        {message.text}
        <span className="font-normal opacity-60">· {formatClock(message.createdAt)}</span>
        {isHandoff && (
          <button type="button" onClick={() => dispatch(contextTabChanged('handoff'))} className="ml-1 underline decoration-dotted underline-offset-2 hover:decoration-solid">
            View brief
          </button>
        )}
      </span>
      <span className="h-px flex-1 bg-slate-200" />
    </div>
  );
}
