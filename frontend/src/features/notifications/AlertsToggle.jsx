import { useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { Icon } from '../../components/ui/index.js';
import { CONVERSATION_STATUS } from '../../constants/conversation.js';
import { HANDOFF_REASON_META } from '../../constants/handoff.js';
import { useGetConversationsQuery } from '../conversations/conversationsApi.js';
import { conversationSelected } from '../conversations/deskSlice.js';

// Desk alerts for a new handoff: a chime (a different one for urgent), a browser notification when the
// tab isn't in view, and the waiting count in the tab title. Off-desk escalation (email, webhook) is the
// API's job — see backend/app/notify/alerts.py.

const KEY = 'baton.desk.alerts'; // 'on' | 'muted'
const TITLE = 'Baton';

function loadPreference() {
  try {
    return localStorage.getItem(KEY) ?? 'on';
  } catch {
    return 'on';
  }
}

function savePreference(value) {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    // Storage blocked: the choice lasts until reload.
  }
}

let audio = null;
function audioContext() {
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) return null;
  audio ??= new Context();
  return audio;
}

function chime(urgent) {
  const ctx = audioContext();
  if (!ctx || ctx.state !== 'running') return; // browsers allow sound only after a click on the page
  const notes = urgent ? [880, 660, 880, 660] : [660, 880];
  notes.forEach((frequency, i) => {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    const start = ctx.currentTime + i * 0.18;
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.2, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16);
    oscillator.connect(gain).connect(ctx.destination);
    oscillator.start(start);
    oscillator.stop(start + 0.17);
  });
}

function notify(fresh, onOpen) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || document.visibilityState === 'visible') return;
  const [first] = fresh;
  const title = fresh.length > 1 ? `${fresh.length} customers are waiting` : `${first.customer.name} is waiting`;
  const reason = HANDOFF_REASON_META[first.handoff?.reason]?.label ?? 'Needs a person';
  const urgent = first.handoff?.priority === 'urgent' ? 'Urgent · ' : '';
  const notification = new Notification(title, { body: `${urgent}${reason} — ${first.subject ?? ''}`, tag: 'baton-handoff', icon: '/favicon.svg' });
  notification.onclick = () => {
    window.focus();
    onOpen(first.id);
    notification.close();
  };
}

/** The bell in the desk header: turns alerts on (asking for notification permission) or mutes them. */
export function AlertsToggle() {
  const dispatch = useDispatch();
  const [preference, setPreference] = useState(loadPreference);
  const [permission, setPermission] = useState(() => ('Notification' in window ? Notification.permission : 'unsupported'));
  const { data = [] } = useGetConversationsQuery();
  const seen = useRef(null);

  const pending = data.filter((c) => c.status === CONVERSATION_STATUS.HANDOFF_PENDING);
  const pendingKey = pending.map((c) => c.id).join(',');

  useEffect(() => {
    document.title = pending.length ? `(${pending.length}) Waiting · ${TITLE}` : TITLE;
  }, [pending.length]);
  useEffect(() => () => void (document.title = TITLE), []);

  useEffect(() => {
    const ids = new Set(pendingKey ? pendingKey.split(',') : []);
    if (seen.current === null) {
      seen.current = ids; // what was already waiting when the desk opened isn't news
      return;
    }
    const fresh = pending.filter((c) => !seen.current.has(c.id));
    seen.current = ids;
    if (!fresh.length || preference !== 'on') return;
    chime(fresh.some((c) => c.handoff?.priority === 'urgent'));
    notify(fresh, (id) => dispatch(conversationSelected(id)));
  }, [pendingKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = async () => {
    audioContext()?.resume(); // this click is what lets the page play sound
    if (preference === 'on' && permission !== 'default') {
      setPreference('muted');
      savePreference('muted');
      return;
    }
    if (permission === 'default') setPermission(await Notification.requestPermission());
    setPreference('on');
    savePreference('on');
    chime(false); // a sample, so the agent knows what to listen for
  };

  const on = preference === 'on';
  const label = !on ? 'Alerts muted — click to turn on' : permission === 'default' ? 'Turn on desktop alerts' : permission === 'denied' ? 'Sound on (desktop notifications are blocked in your browser)' : 'Alerts on — click to mute';
  return (
    <button
      type="button"
      onClick={toggle}
      title={label}
      aria-label={label}
      className={`relative rounded-full p-1.5 ring-1 transition hover:bg-white/10 ${on ? 'text-slate-200 ring-slate-600' : 'text-slate-500 ring-slate-700'}`}
    >
      <Icon name={on ? 'bell' : 'bellSlash'} className="size-4" />
      {on && permission === 'default' && <span className="absolute -top-0.5 -right-0.5 size-2 rounded-full bg-amber-400" />}
    </button>
  );
}
