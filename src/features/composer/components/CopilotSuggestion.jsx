import { useState } from 'react';
import { Button, Icon } from '../../../components/ui/index.js';
import { formatPercent } from '../../../utils/format.js';

/**
 * After handoff the bot doesn't disappear — it becomes the agent's copilot,
 * drafting a grounded reply the agent can edit or ignore.
 */
export function CopilotSuggestion({ copilot, onUse }) {
  const [dismissedFor, setDismissedFor] = useState(null);
  if (!copilot || dismissedFor === copilot.text) return null;

  return (
    <div className="mb-3 rounded-xl border border-sky-200 bg-sky-50/70 p-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-xs font-semibold text-sky-800">
          <Icon name="sparkles" className="size-4" />
          Suggested reply
          <span className="font-normal text-sky-700/80">
            · {formatPercent(copilot.confidence)} match · {copilot.sources[0]?.title}
          </span>
        </p>
        <button type="button" onClick={() => setDismissedFor(copilot.text)} className="rounded p-0.5 text-sky-700/70 hover:bg-sky-100 hover:text-sky-900" aria-label="Dismiss suggestion">
          <Icon name="x" className="size-4" />
        </button>
      </div>
      <p className="text-sm text-slate-700">{copilot.text}</p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <p className="truncate text-[11px] text-slate-500">For: “{copilot.basedOn}”</p>
        <Button size="sm" variant="secondary" icon="copy" onClick={() => onUse(copilot.text)}>
          Use draft
        </Button>
      </div>
    </div>
  );
}
