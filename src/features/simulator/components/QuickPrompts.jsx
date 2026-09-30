// Each prompt exercises a different branch of the handoff policy.
const PROMPTS = [
  { label: 'Answerable', text: 'How long does shipping take to Canada?' },
  { label: 'Vague', text: 'My thing is acting weird' },
  { label: 'Asks for human', text: 'Can I talk to a real person please?' },
  { label: 'Frustrated', text: 'This is ridiculous, I’ve asked three times already!!' },
  { label: 'Sensitive', text: 'I see an unauthorized charge of $89.00 on my card' },
  { label: 'Out of scope', text: 'Do you offer bulk pricing for a team of 40 with net-30 invoicing?' },
];

export function QuickPrompts({ onPick, disabled }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {PROMPTS.map((prompt) => (
        <button
          key={prompt.label}
          type="button"
          disabled={disabled}
          onClick={() => onPick(prompt.text)}
          title={prompt.text}
          className="rounded-full bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-slate-100 hover:text-slate-900 disabled:opacity-50"
        >
          {prompt.label}
        </button>
      ))}
    </div>
  );
}
