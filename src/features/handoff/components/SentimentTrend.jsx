import { Badge, Section } from '../../../components/ui/index.js';
import { HANDOFF_POLICY } from '../../../constants/handoff.js';

const LABEL_TONE = { Frustrated: 'rose', Negative: 'amber', Neutral: 'slate', Positive: 'emerald' };

export const sentimentLabel = (score) =>
  score <= HANDOFF_POLICY.sentimentThreshold ? 'Frustrated' : score < -0.15 ? 'Negative' : score > 0.25 ? 'Positive' : 'Neutral';

// Maps sentiment (-1…1) onto the SVG's 0…40 vertical space.
const y = (value) => 20 - value * 18;

/** Per-turn sentiment sparkline with the handoff threshold drawn in. */
export function SentimentTrend({ trend, current }) {
  const label = sentimentLabel(current);
  // A single reading is drawn as a flat line so there's always something to see.
  const series = trend.length === 1 ? [trend[0], trend[0]] : trend;
  const points = series.map((value, i) => [(i * 100) / Math.max(1, series.length - 1), y(value)]);

  return (
    <Section title="Sentiment" icon="frown" aside={<Badge tone={LABEL_TONE[label]}>{label} · {current.toFixed(2)}</Badge>}>
      {trend.length ? (
        <svg viewBox="-3 0 106 40" preserveAspectRatio="none" className="h-12 w-full overflow-visible" role="img" aria-label={`Sentiment trend, currently ${label}`}>
          <line x1="0" x2="100" y1={y(0)} y2={y(0)} className="stroke-slate-200" strokeWidth="0.75" vectorEffect="non-scaling-stroke" />
          <line
            x1="0"
            x2="100"
            y1={y(HANDOFF_POLICY.sentimentThreshold)}
            y2={y(HANDOFF_POLICY.sentimentThreshold)}
            className="stroke-rose-300"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />
          <polyline points={points.map((p) => p.join(',')).join(' ')} fill="none" className="stroke-indigo-500" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        </svg>
      ) : (
        <p className="text-xs text-slate-500">No customer messages yet.</p>
      )}
      <p className="mt-1 text-[11px] text-slate-400">Dashed line = handoff threshold ({HANDOFF_POLICY.sentimentThreshold})</p>
    </Section>
  );
}
