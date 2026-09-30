import { Badge, ScoreMeter, Section } from '../../../components/ui/index.js';

const OUTCOME = {
  answered: { label: 'Answered', tone: 'emerald' },
  clarified: { label: 'Asked to clarify', tone: 'amber' },
  handed_off: { label: 'Handed off', tone: 'rose' },
};

/** What the bot already tried — so the agent doesn't repeat an answer that didn't land. */
export function BotAttempts({ attempts }) {
  return (
    <Section title="What the bot tried" icon="bot" aside={<span className="text-xs text-slate-400">{attempts.length}</span>}>
      {attempts.length ? (
        <ol className="relative space-y-3 border-l border-slate-200 pl-4">
          {attempts.map((attempt) => {
            const outcome = OUTCOME[attempt.outcome];
            return (
              <li key={attempt.questionMessageId} className="relative">
                <span className="absolute top-1.5 -left-[21px] size-2.5 rounded-full bg-white ring-2 ring-slate-300" aria-hidden="true" />
                <p className="text-sm text-slate-700">“{attempt.question}”</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge tone={outcome.tone}>{outcome.label}</Badge>
                  {attempt.sourceTitle && <span className="truncate text-xs text-slate-500">{attempt.sourceTitle}</span>}
                </div>
                <ScoreMeter value={attempt.confidence} label="Match" className="mt-1.5" />
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-xs text-slate-500">The bot hadn’t attempted an answer before stepping aside.</p>
      )}
    </Section>
  );
}
