import { Icon, Section } from '../../../components/ui/index.js';
import { PRIORITY_META } from '../../../constants/handoff.js';
import { formatClock } from '../../../utils/format.js';

/** What the customer said after the bot stepped aside — newest context first in line for the agent. */
export function AddedWhileWaiting({ messages = [], escalated }) {
  if (!messages.length && !escalated) return null;
  return (
    <Section title="Added while waiting" icon="chat" aside={<span className="text-xs text-slate-400">{messages.length}</span>}>
      {escalated && (
        <p className="mb-2 flex items-start gap-1.5 rounded-lg bg-rose-50 px-2.5 py-2 text-xs text-rose-800 ring-1 ring-rose-100">
          <Icon name="warning" className="mt-px size-3.5 shrink-0" />
          <span>
            Priority raised from {PRIORITY_META[escalated.from]?.label ?? escalated.from} to <strong>{PRIORITY_META[escalated.to]?.label ?? escalated.to}</strong> — {escalated.why}
          </span>
        </p>
      )}
      <ul className="space-y-1.5">
        {messages.map((m) => (
          <li key={m.id} className="rounded-lg bg-white px-2.5 py-2 text-sm text-slate-700 ring-1 ring-slate-200">
            {m.text}
            <span className="ml-1.5 text-[11px] text-slate-400">{formatClock(m.at)}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}
