import { useState } from 'react';
import { Icon, Spinner } from '../../../components/ui/index.js';

export function SimulatorInput({ onSend, sending, disabled }) {
  const [text, setText] = useState('');

  const submit = (event) => {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    onSend(value);
    setText('');
  };

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={disabled}
        placeholder="Type as the customer…"
        className="min-w-0 flex-1 rounded-lg border-0 px-3 py-2 text-sm ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-slate-900 focus:outline-none disabled:bg-slate-100"
      />
      <button type="submit" disabled={disabled || sending || !text.trim()} className="rounded-lg bg-slate-900 p-2 text-white hover:bg-slate-700 disabled:opacity-40" aria-label="Send as customer">
        {sending ? <Spinner className="size-4" /> : <Icon name="send" className="size-4" />}
      </button>
    </form>
  );
}
