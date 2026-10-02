import { useState } from 'react';
import { Section } from '../../../components/ui/index.js';

export function SuggestedNextSteps({ steps }) {
  const [done, setDone] = useState(() => new Set());
  if (!steps.length) return null;

  const toggle = (index) =>
    setDone((prev) => {
      const next = new Set(prev);
      next.has(index) ? next.delete(index) : next.add(index);
      return next;
    });

  return (
    <Section title="Suggested next steps" icon="checkCircle">
      <ul className="space-y-1.5">
        {steps.map((step, i) => (
          <li key={i}>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={done.has(i)} onChange={() => toggle(i)} className="mt-0.5 size-4 rounded border-slate-300 accent-indigo-600" />
              <span className={done.has(i) ? 'text-slate-400 line-through' : ''}>{step}</span>
            </label>
          </li>
        ))}
      </ul>
    </Section>
  );
}
