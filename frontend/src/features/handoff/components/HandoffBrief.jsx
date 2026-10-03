import { Icon, Section } from '../../../components/ui/index.js';
import { AddedWhileWaiting } from './AddedWhileWaiting.jsx';
import { BotAttempts } from './BotAttempts.jsx';
import { EntityList } from './EntityList.jsx';
import { HandoffReasonCard } from './HandoffReasonCard.jsx';
import { HandoffSummary } from './HandoffSummary.jsx';
import { OpenQuestions } from './OpenQuestions.jsx';
import { SentimentTrend } from './SentimentTrend.jsx';
import { SuggestedNextSteps } from './SuggestedNextSteps.jsx';

/**
 * The handoff packet, ordered the way an agent reads it:
 * why → what the customer added since → what's going on → what's still open → what to do → the facts → the history.
 */
export function HandoffBrief({ handoff, replyEmail }) {
  return (
    <>
      <Section title="Why the bot stepped aside" icon="arrowRight">
        <HandoffReasonCard handoff={handoff} />
        {handoff.offline && (
          <p className="mt-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-2 text-xs text-amber-900 ring-1 ring-amber-100">
            <Icon name="moon" className="mt-px size-3.5 shrink-0" />
            Arrived while nobody was available — the customer was told the team would reply later.
          </p>
        )}
        {replyEmail && (
          <p className="mt-2 flex items-start gap-1.5 text-xs text-slate-500">
            <Icon name="mail" className="mt-px size-3.5 shrink-0" />
            If the customer has left the chat, your replies are also emailed to {replyEmail}.
          </p>
        )}
      </Section>
      <AddedWhileWaiting messages={handoff.addedWhileWaiting} escalated={handoff.escalated} />
      <HandoffSummary summary={handoff.summary} intent={handoff.intent} />
      <OpenQuestions questions={handoff.openQuestions} />
      <SuggestedNextSteps steps={handoff.suggestedNextSteps} />
      <EntityList entities={handoff.entities} />
      <SentimentTrend trend={handoff.sentiment.trend} current={handoff.sentiment.current} />
      <BotAttempts attempts={handoff.botAttempts} />
    </>
  );
}
