import { useMemo } from 'react';
import { Badge, EmptyState, ScoreMeter, Section } from '../../../components/ui/index.js';
import { HANDOFF_POLICY } from '../../../constants/handoff.js';

// Every article the retriever surfaced in this conversation (bot replies + copilot draft), best score wins.
function collectSources(conversation) {
  const byId = new Map();
  const all = [
    ...conversation.messages.flatMap((m) => m.meta?.sources ?? []),
    ...(conversation.copilot?.sources ?? []),
  ];
  for (const source of all) {
    if (source.score < HANDOFF_POLICY.copilotThreshold) continue;
    const existing = byId.get(source.id);
    if (!existing || source.score > existing.score) byId.set(source.id, source);
  }
  return [...byId.values()].sort((a, b) => b.score - a.score);
}

export function KnowledgeSources({ conversation }) {
  const sources = useMemo(() => collectSources(conversation), [conversation]);

  if (!sources.length) {
    return <EmptyState icon="book" title="No articles retrieved yet" description="Sources the bot or copilot pulls from the knowledge base will appear here." />;
  }

  return (
    <Section title="Retrieved from the knowledge base" icon="book" aside={<span className="text-xs text-slate-400">{sources.length}</span>}>
      <ul className="space-y-3">
        {sources.map((source) => (
          <li key={source.id} className="rounded-lg p-3 ring-1 ring-slate-200">
            <div className="flex items-start justify-between gap-2">
              <a href={source.url} onClick={(e) => e.preventDefault()} className="text-sm font-medium text-indigo-700 hover:underline" title={source.url}>
                {source.title}
              </a>
              <Badge tone="slate">{source.category}</Badge>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">{source.snippet}</p>
            <ScoreMeter value={source.score} label="Relevance" className="mt-2" />
          </li>
        ))}
      </ul>
    </Section>
  );
}
