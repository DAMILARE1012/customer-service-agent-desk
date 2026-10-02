import { useState } from 'react';
import { Avatar, Badge, Icon } from '../../../components/ui/index.js';
import { CLOSED_REASON_META, CUSTOMER_TIER_META } from '../../../constants/conversation.js';
import { StatusBadge } from '../../conversations/components/StatusBadge.jsx';
import { ConversationActions } from '../../handoff/components/ConversationActions.jsx';
import { TranscriptDrawer } from './TranscriptDrawer.jsx';

/** This session continues an earlier one: say so, and let the agent read it. */
function FollowUpOf({ previous }) {
  const [open, setOpen] = useState(false);
  const closed = CLOSED_REASON_META[previous.closedReason];
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="mt-0.5 inline-flex max-w-full items-center gap-1 text-left text-[11px] text-indigo-600 hover:text-indigo-500">
        <Icon name="refresh" className="size-3 shrink-0" />
        <span className="truncate">
          Follow-up of “{previous.subject ?? 'an earlier chat'}”{closed ? ` · ${closed.label}` : ''}{previous.handledBy ? ` by ${previous.handledBy}` : ''}
        </span>
      </button>
      {open && <TranscriptDrawer conversationId={previous.id} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ThreadHeader({ conversation }) {
  const { customer, subject, status } = conversation;
  const tier = CUSTOMER_TIER_META[customer.tier];

  return (
    <header className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar name={customer.name} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-sm font-semibold text-slate-900">{customer.name}</h2>
            <Badge tone={tier.tone}>{tier.label}</Badge>
            <StatusBadge status={status} />
          </div>
          <p className="truncate text-xs text-slate-500">{subject ?? customer.email}</p>
          {conversation.followUpOf && <FollowUpOf previous={conversation.followUpOf} />}
        </div>
      </div>
      <ConversationActions conversation={conversation} />
    </header>
  );
}
