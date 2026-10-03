import { CONVERSATION_STATUS } from '../../../constants/conversation.js';
import { formatRelative } from '../../../utils/format.js';

// The customer's widget sends a heartbeat every 15 s while their page is open (slower in a background tab)
// and says when the page closes. Thresholds follow the API's rules in backend/app/conversation/sessions.py.
const HERE_MS = 45_000;
const GONE_MS = 180_000;

/** Is the customer still there? { label, tone } or null for a closed conversation. */
export function customerPresence(conversation, now = Date.now()) {
  if (!conversation || conversation.status === CONVERSATION_STATUS.RESOLVED) return null;
  if (conversation.customerLeftAt) return { label: `Left ${formatRelative(conversation.customerLeftAt, now)}`, tone: 'left' };
  const seen = conversation.customerSeenAt;
  if (!seen) return null;
  const quiet = now - seen;
  if (quiet < HERE_MS) return { label: 'Here', tone: 'here' };
  if (quiet < GONE_MS) return { label: 'Away', tone: 'away' };
  return { label: `Left ${formatRelative(seen, now)}`, tone: 'left' };
}

const DOT = { here: 'bg-emerald-500', away: 'bg-amber-400', left: 'bg-slate-300' };
const TEXT = { here: 'text-emerald-700', away: 'text-amber-700', left: 'text-slate-500' };

/** A dot and a word — "Here", "Away", "Left 3 min ago" — so the agent knows whether anyone is reading. */
export function CustomerPresence({ conversation, now, compact = false }) {
  const presence = customerPresence(conversation, now);
  if (!presence) return null;
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium ${TEXT[presence.tone]}`} title={`Customer: ${presence.label}`}>
      <span className={`size-1.5 rounded-full ${DOT[presence.tone]}`} aria-hidden="true" />
      {compact ? (presence.tone === 'here' ? '' : presence.label) : presence.label}
    </span>
  );
}
