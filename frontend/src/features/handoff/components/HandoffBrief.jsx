import { Section } from '../../../components/ui/index.js';
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
export function HandoffBrief({ handoff }) {
  return (
    <>
      <Section title="Why the bot stepped aside" icon="arrowRight">
        <HandoffReasonCard handoff={handoff} />
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
