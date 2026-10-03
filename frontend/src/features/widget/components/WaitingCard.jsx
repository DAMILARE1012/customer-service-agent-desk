import { useState } from 'react';
import { Icon } from '../../../components/ui/index.js';
import { errorMessage } from '../../../utils/format.js';
import { useLeaveContactMutation } from '../../chat/chatApi.js';

function ordinal(n) {
  if (n % 100 >= 11 && n % 100 <= 13) return `${n}th`;
  return `${n}${{ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'}`;
}

/** While a customer waits for a person: their place in line — or, when nobody is in, when the team is
 * back and where the reply will go (asking for an email if we have none). */
export function WaitingCard({ conversationId, waiting }) {
  const [leaveContact, state] = useLeaveContactMutation();
  const [email, setEmail] = useState('');

  if (waiting.teamAvailable) {
    const line = waiting.position <= 1 ? 'You’re next in line' : `You’re ${ordinal(waiting.position)} in line`;
    const wait = waiting.estimatedMinutes ? ` · usually about ${waiting.estimatedMinutes} min` : '';
    return (
      <div className="flex items-center gap-2 border-t border-indigo-100 bg-indigo-50 px-4 py-2 text-xs text-indigo-800" role="status">
        <Icon name="clock" className="size-4 shrink-0" />
        <span>
          {line}
          {wait}. You can keep adding details below.
        </span>
      </div>
    );
  }

  const submit = (event) => {
    event.preventDefault();
    if (email.trim()) leaveContact({ conversationId, email: email.trim() });
  };
  return (
    <div className="space-y-2 border-t border-amber-100 bg-amber-50 px-4 py-2.5 text-xs text-amber-900" role="status">
      <p className="flex items-start gap-2">
        <Icon name="moon" className="mt-px size-4 shrink-0" />
        <span>
          Our team is away{waiting.backAtText ? ` — back ${waiting.backAtText}` : ''}.{' '}
          {waiting.replyEmail ? `We’ll email the reply to ${waiting.replyEmail}.` : 'Leave your email and we’ll reply there.'}
        </span>
      </p>
      {waiting.askForEmail && (
        <form onSubmit={submit} className="flex gap-1.5">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            aria-label="Your email"
            autoComplete="email"
            className="min-w-0 flex-1 rounded-lg border-0 bg-white px-2.5 py-1.5 text-xs text-slate-800 ring-1 ring-amber-200 focus:ring-2 focus:ring-amber-500"
          />
          <button type="submit" disabled={state.isLoading} className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-500 disabled:opacity-50">
            Send
          </button>
        </form>
      )}
      {state.error && <p className="text-rose-700">{errorMessage(state.error)}</p>}
    </div>
  );
}
