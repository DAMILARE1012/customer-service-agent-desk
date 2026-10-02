import { Badge, Section } from '../../../components/ui/index.js';
import { formatPercent } from '../../../utils/format.js';

export function HandoffSummary({ summary, intent }) {
  return (
    <Section
      title="Summary"
      icon="sparkles"
      aside={intent && <Badge tone="slate">{intent.label} · {formatPercent(intent.confidence)}</Badge>}
    >
      <p className="text-sm leading-relaxed text-slate-700">{summary}</p>
    </Section>
  );
}
