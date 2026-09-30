import { Badge, Icon, Section } from '../../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { HANDOFF_POLICY } from '../../../constants/handoff.js';
import { formatPercent } from '../../../utils/format.js';
import { BotAttempts } from './BotAttempts.jsx';
import { EntityList } from './EntityList.jsx';
import { SentimentTrend } from './SentimentTrend.jsx';

function WatchRow({ label, value, ok, hint }) {
  return (
    <li className="flex items-center justify-between gap-3 py-1.5">
      <span className="text-sm text-slate-600">{label}</span>
      <span className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-800 tabular-nums">{value}</span>
        <Badge tone={ok ? 'emerald' : 'amber'} icon={ok ? 'check' : 'warning'}>{ok ? 'OK' : hint}</Badge>
      </span>
    </li>
  );
}

/**
 * While the bot is still in charge, show the same signals the handoff policy watches,
 * so an agent can see a handoff coming (and take over early if they want).
 */
export function LiveBotInsights({ conversation }) {
  const { insights, handoffHistory, status } = conversation;
  const { lastConfidence, sentiment, failedAttempts } = insights;
  const intro =
    status === CONVERSATION_STATUS.RESOLVED
      ? 'Resolved by the assistant — no handoff was needed.'
      : 'The assistant is handling this chat. It will step aside automatically if any of these cross the line.';

  return (
    <>
      <Section title="Handoff watch" icon="bot">
        <p className="mb-2 flex items-start gap-1.5 text-xs text-slate-500">
          <Icon name="bot" className="mt-0.5 size-3.5 shrink-0" />
          {intro}
        </p>
        <ul className="divide-y divide-slate-100">
          <WatchRow
            label="Last answer confidence"
            value={formatPercent(lastConfidence)}
            ok={lastConfidence == null || lastConfidence >= HANDOFF_POLICY.answerThreshold}
            hint="Low"
          />
          <WatchRow
            label="Sentiment"
            value={sentiment.current.toFixed(2)}
            ok={sentiment.current > HANDOFF_POLICY.sentimentThreshold + 0.2}
            hint="Dropping"
          />
          <WatchRow
            label="Unanswered in a row"
            value={`${failedAttempts} / ${HANDOFF_POLICY.maxFailedAttempts}`}
            ok={failedAttempts === 0}
            hint="At risk"
          />
        </ul>
        {handoffHistory.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Handed off {handoffHistory.length}× before in this conversation — last returned by {handoffHistory.at(-1).acceptedBy?.name ?? 'an agent'}.
          </p>
        )}
      </Section>
      <EntityList entities={insights.entities} title="Collected so far" />
      <SentimentTrend trend={sentiment.trend} current={sentiment.current} />
      <BotAttempts attempts={insights.attempts} />
    </>
  );
}
