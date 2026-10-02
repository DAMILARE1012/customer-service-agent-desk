import { useState } from 'react';
import { Icon, Section } from '../../../components/ui/index.js';

function EntityRow({ entity }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(entity.value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable — ignore */
    }
  };

  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-1.5 ring-1 ring-slate-200">
      <dt className="text-xs text-slate-500">{entity.label}</dt>
      <dd className="flex items-center gap-1.5 font-mono text-xs font-medium text-slate-800">
        {entity.value}
        <button type="button" onClick={copy} className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700" aria-label={`Copy ${entity.label}`}>
          <Icon name={copied ? 'check' : 'copy'} className="size-3.5" />
        </button>
      </dd>
    </div>
  );
}

/** Structured facts the bot pulled out of the conversation, so the agent never asks twice. */
export function EntityList({ entities, title = 'What the customer already told us' }) {
  return (
    <Section title={title} icon="user">
      {entities.length ? (
        <dl className="space-y-1.5">
          {entities.map((entity) => (
            <EntityRow key={`${entity.type}:${entity.value}`} entity={entity} />
          ))}
        </dl>
      ) : (
        <p className="text-xs text-slate-500">No order numbers, emails or amounts mentioned yet.</p>
      )}
    </Section>
  );
}
