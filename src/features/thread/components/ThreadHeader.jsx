import { Avatar, Badge } from '../../../components/ui/index.js';
import { CUSTOMER_TIER_META } from '../../../constants/conversation.js';
import { StatusBadge } from '../../conversations/components/StatusBadge.jsx';
import { ConversationActions } from '../../handoff/components/ConversationActions.jsx';

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
        </div>
      </div>
      <ConversationActions conversation={conversation} />
    </header>
  );
}
