import { config } from '../../config.js';

// Widget sessions (real backend). Customers never sign in to Baton: an anonymous visitor gets a session
// from POST /widget/session; a customer already signed in to the website gets one by passing the identity
// token the website's backend signed for them. Both are kept in this frame's storage so a returning
// customer sees their chat — the visitor and the identified session separately, so signing out of the
// website falls back to the visitor's own history.

const KEYS = { visitor: 'baton.widget.visitor', identified: 'baton.widget.identified' };

function read(key) {
  try {
    const session = JSON.parse(localStorage.getItem(key));
    return session && session.expiresAt > Date.now() + 60_000 ? session : null;
  } catch {
    return null;
  }
}

function write(key, session) {
  try {
    if (session) localStorage.setItem(key, JSON.stringify(session));
    else localStorage.removeItem(key);
  } catch {
    // Storage blocked (private mode, partitioned third-party storage): the session lasts this page view.
  }
}

/** The user id inside an identity token — only to tell whose session we hold; the API verifies it. */
export function identitySubject(identityToken) {
  try {
    const part = identityToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(part.padEnd(part.length + ((4 - (part.length % 4)) % 4), '='))).sub ?? null;
  } catch {
    return null;
  }
}

async function create(identityToken) {
  const res = await fetch(`${config.api.baseUrl}/widget/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(identityToken ? { identity: identityToken } : {}),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.message ?? 'Chat is unavailable right now.');
  return body;
}

/** A session already held for this person (no network), or null. */
export function storedSession(identityToken) {
  if (!identityToken) return read(KEYS.visitor);
  const held = read(KEYS.identified);
  return held && held.subject === identitySubject(identityToken) ? held : null;
}

const inFlight = new Map();

/** The session for this person, creating one if needed (one request at a time per person). */
export function sessionFor(identityToken) {
  const held = storedSession(identityToken);
  if (held) return Promise.resolve(held);
  const key = identityToken ?? '';
  if (!inFlight.has(key)) {
    const request = create(identityToken)
      .then((body) => {
        const fresh = identityToken ? { ...body, subject: identitySubject(identityToken) } : body;
        write(identityToken ? KEYS.identified : KEYS.visitor, fresh);
        return fresh;
      })
      .finally(() => inFlight.delete(key));
    inFlight.set(key, request);
  }
  return inFlight.get(key);
}

/** Drop a session the API no longer accepts (expired, or the customer's data was erased). */
export function forgetSession(session) {
  write(session?.kind === 'identified' ? KEYS.identified : KEYS.visitor, null);
}
