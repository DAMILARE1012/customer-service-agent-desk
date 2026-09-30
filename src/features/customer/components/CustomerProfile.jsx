import { Avatar, Badge, Section } from '../../../components/ui/index.js';
import { CUSTOMER_TIER_META } from '../../../constants/conversation.js';
import { formatCurrency, formatDate } from '../../../utils/format.js';

function Stat({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className="text-sm font-semibold text-slate-800 tabular-nums">{value}</dd>
    </div>
  );
}

export function CustomerProfile({ customer }) {
  const tier = CUSTOMER_TIER_META[customer.tier];

  return (
    <>
      <Section title="Customer" icon="user">
        <div className="flex items-center gap-3">
          <Avatar name={customer.name} size="lg" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900">{customer.name}</p>
            <p className="truncate text-xs text-slate-500">{customer.email}</p>
            <p className="text-xs text-slate-500">{customer.location}</p>
          </div>
          <Badge tone={tier.tone} className="ml-auto">{tier.label}</Badge>
        </div>
      </Section>
      <Section title="Account" icon="chat">
        <dl className="grid grid-cols-2 gap-2">
          <Stat label="Customer since" value={formatDate(customer.customerSince)} />
          <Stat label="Lifetime value" value={formatCurrency(customer.lifetimeValue)} />
          <Stat label="Orders" value={customer.orderCount} />
          <Stat label="Past conversations" value={customer.previousConversations} />
        </dl>
      </Section>
    </>
  );
}
