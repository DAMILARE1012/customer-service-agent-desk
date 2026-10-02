import { useState } from 'react';
import { Icon, Spinner } from '../../../components/ui/index.js';

/** Enter sends, Shift+Enter adds a line. */
export function ChatComposer({ onSend, sending, placeholder = 'Ask a question…' }) {
  const [text, setText] = useState('');

  const submit = (event) => {
    event?.preventDefault();
    const value = text.trim();
    if (!value || sending) return;
    onSend(value);
    setText('');
  };

  return (
    <form onSubmit={submit} className="flex items-end gap-2 rounded-2xl bg-white p-2 shadow-sm ring-1 ring-slate-200 focus-within:ring-2 focus-within:ring-indigo-500">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) submit(e);
        }}
        rows={1}
        maxLength={4000}
        placeholder={placeholder}
        aria-label="Message"
        className="max-h-40 min-h-[40px] flex-1 resize-none border-0 bg-transparent px-2 py-2 text-sm [field-sizing:content] placeholder:text-slate-400 focus:ring-0 focus:outline-none"
      />
      <button
        type="submit"
        disabled={!text.trim() || sending}
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-xl bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:opacity-40"
        aria-label="Send"
      >
        {sending ? <Spinner className="size-4" /> : <Icon name="send" className="size-4" />}
      </button>
    </form>
  );
}
