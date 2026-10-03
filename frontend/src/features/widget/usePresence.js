import { useEffect } from 'react';
import { config } from '../../config.js';

const HEARTBEAT_MS = 15_000;

/**
 * Tell the API the customer is still here — every 15 s while the page is open, whether the chat panel is open
 * or minimised — and that they're leaving when the page closes. The API ends the chat from these signals
 * (see backend/app/conversation/sessions.py); moving to another page of the site just resumes the heartbeat.
 *
 * Browsers slow timers in background tabs (to about once a minute), which the API allows for.
 */
export function usePresence(conversationId, getToken) {
  useEffect(() => {
    if (!conversationId || !config.api.baseUrl) return undefined; // the in-browser demo backend has no sweeper
    const url = `${config.api.baseUrl}/me/conversations/${conversationId}/presence`;
    const send = (state, keepalive = false) => {
      const token = getToken();
      if (!token) return;
      fetch(url, {
        method: 'POST',
        keepalive, // lets the request finish while the page unloads (sendBeacon can't send the Authorization header)
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ state }),
      }).catch(() => {}); // presence is best-effort: a missed beat is covered by the next one
    };

    send('here');
    const timer = setInterval(() => send('here'), HEARTBEAT_MS);
    const onHide = () => send('left', true);
    const onShow = () => send('here'); // back from another tab, or restored from the back/forward cache
    const onVisibility = () => document.visibilityState === 'visible' && onShow();
    window.addEventListener('pagehide', onHide);
    window.addEventListener('pageshow', onShow);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      clearInterval(timer);
      window.removeEventListener('pagehide', onHide);
      window.removeEventListener('pageshow', onShow);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [conversationId, getToken]);
}
