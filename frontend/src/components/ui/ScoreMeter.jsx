import { formatPercent } from '../../utils/format.js';

const barColor = (value) => (value >= 0.5 ? 'bg-emerald-500' : value >= 0.35 ? 'bg-amber-500' : 'bg-rose-500');

/** Horizontal 0–1 meter for retrieval / confidence scores. */
export function ScoreMeter({ value, label, className = '' }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {label && <span className="text-xs text-slate-500">{label}</span>}
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${barColor(value)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-xs font-medium text-slate-600 tabular-nums">{formatPercent(value)}</span>
    </div>
  );
}
