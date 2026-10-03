import { memo } from 'react';
import { Avatar, Icon } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS, SENDER } from '../../../constants/conversation.js';
import { PRIORITY_META } from '../../../constants/handoff.js';
import { SOLID_TONES } from '../../../components/ui/tones.js';
import { formatRelative } from '../../../utils/format.js';
import { HandoffReasonBadge } from '../../handoff/components/HandoffReasonBadge.jsx';
import { WaitTimer } from '../../handoff/components/WaitTimer.jsx';
import { StatusBadge } from './StatusBadge.jsx';

const SENDER_PREFIX = { [SENDER.BOT]: 'Bot: ', [SENDER.AGENT]: 'Agent: ' };

function ConversationListItemBase({ conversation, selected, onSelect, now }) {
  const { customer, status, handoff, lastMessage, subject, assignee } = conversation;
  const pending = status === CONVERSATION_STATUS.HANDOFF_PENDING;
  const priorityTone = pending ? PRIORITY_META[handoff.priority].tone : null;

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(conversation.id)}
        className={`relative flex w-full gap-3 px-4 py-3 text-left transition ${selected ? 'bg-indigo-50/70' : 'hover:bg-slate-50'}`}
      >
        {priorityTone && <span className={`absolute inset-y-2 left-0 w-1 rounded-r ${SOLID_TONES[priorityTone]}`} aria-hidden="true" />}
        <Avatar name={customer.name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <p className="truncate text-sm font-semibold text-slate-900">{customer.name}</p>
            {pending ? (
              <WaitTimer since={handoff.requestedAt} />
            ) : (
              <span className="shrink-0 text-xs text-slate-400">{formatRelative(conversation.updatedAt, now)}</span>
            )}
          </div>
          <p className="truncate text-xs text-slate-600">{subject ?? 'New conversation'}</p>
          {lastMessage && (
            <p className="mt-0.5 truncate text-xs text-slate-400">
              {SENDER_PREFIX[lastMessage.sender] ?? ''}
              {lastMessage.text}
            </p>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {pending ? <HandoffReasonBadge reason={handoff.reason} /> : <StatusBadge status={status} />}
            {pending && handoff.addedWhileWaiting > 0 && (
              <span className="rounded-full bg-indigo-600 px-1.5 text-[10px] font-semibold text-white" title="Messages the customer sent while waiting">
                +{handoff.addedWhileWaiting} new
              </span>
            )}
            {pending && handoff.priority !== 'normal' && (
              <span className="text-[11px] font-medium text-slate-500">{PRIORITY_META[handoff.priority].label}</span>
            )}
            {assignee && status === CONVERSATION_STATUS.AGENT_ACTIVE && (
              <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                <Icon name="user" className="size-3" />
                {assignee.name}
              </span>
            )}
          </div>
        </div>
      </button>
    </li>
  );
}

export const ConversationListItem = memo(ConversationListItemBase);
