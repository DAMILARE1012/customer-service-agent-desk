import { useState } from 'react';
import { Badge, Icon, Section, Spinner } from '../../../components/ui/index.js';
import { CLOSED_REASON_META, STATUS_META } from '../../../constants/conversation.js';
import { HANDOFF_REASON_META } from '../../../constants/handoff.js';
import { formatRelative } from '../../../utils/format.js';
import { TranscriptDrawer } from '../../thread/components/TranscriptDrawer.jsx';
import { useGetCustomerTimelineQuery } from '../customerApi.js';

/**
 * Every session this customer has had, newest first. This is where history lives: the agent sees it,
 * the assistant starts every session with a clean slate.
 */
export function CustomerTimeline({ customerId, currentId }) {
  const { data: sessions = [], isLoading } = useGetCustomerTimelineQuery(customerId, { pollingInterval: 30_000 });
  const [openId, setOpenId] = useState(null);
  const past = sessions.filter((s) => s.id !== currentId);

  return (
    <Section title={`Past conversations · ${past.length}`} icon="clock">
      {isLoading && <Spinner className="size-4 text-slate-400" />}
      {!isLoading && past.length === 0 && <p className="text-xs text-slate-500">First conversation with this customer.</p>}
      <ol className="space-y-2">
        {past.map((session) => {
          const closed = CLOSED_REASON_META[session.closedReason];
          const reason = session.handoffReason && HANDOFF_REASON_META[session.handoffReason];
          return (
            <li key={session.id}>
              <button
                type="button"
                onClick={() => setOpenId(session.id)}
                className="w-full rounded-lg px-3 py-2.5 text-left ring-1 ring-slate-200 transition hover:bg-slate-50 hover:ring-indigo-200"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-slate-800">{session.subject ?? 'No messages'}</p>
                  <span className="shrink-0 text-[11px] text-slate-400">{formatRelative(session.closedAt ?? session.createdAt)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  {closed ? <Badge tone={closed.tone}>{closed.label}</Badge> : <Badge tone={STATUS_META[session.status].tone}>{STATUS_META[session.status].label}</Badge>}
                  {reason && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-slate-500">
                      <Icon name={reason.icon} className="size-3" />
                      {reason.label}
                    </span>
                  )}
                  {session.handledBy && <span className="text-[11px] text-slate-500">· {session.handledBy}</span>}
                </div>
                <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-slate-600">{session.summary}</p>
              </button>
            </li>
          );
        })}
      </ol>
      {openId && <TranscriptDrawer conversationId={openId} onClose={() => setOpenId(null)} />}
    </Section>
  );
}
