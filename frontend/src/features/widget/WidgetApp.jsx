import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { baseApi, setTokenSource } from '../../api/baseApi.js';
import { signedIn } from '../../auth/authSlice.js';
import { config } from '../../config.js';
import { useGetMyConversationsQuery } from '../chat/chatApi.js';
import { isOpen } from '../chat/chatStatus.js';
import { Launcher } from './components/Launcher.jsx';
import { WidgetPanel } from './components/WidgetPanel.jsx';
import { usePresence } from './usePresence.js';
import { forgetSession, sessionFor, storedSession } from './widgetSession.js';

const asCustomer = (session) => ({ sub: session.customer.id, name: session.customer.name, email: null, roles: ['customer'] });

/**
 * The customer chat widget: a launcher over the website that opens a compact chat panel.
 *
 * identity  identity token from the website's backend for a signed-in customer (null = guest)
 * demoUser  mock backend only: who is chatting (there are no real sessions in demo mode)
 * onState   called with { open, unread } — the embed script sizes the iframe from it
 * command   { type: 'baton:open' | 'baton:close' } from the website (Baton.open() / Baton.close())
 */
export function WidgetApp({ identity = null, demoUser = null, onState, command = null }) {
  const dispatch = useDispatch();
  const mock = !config.api.baseUrl;
  const [open, setOpen] = useState(false);
  const [session, setSession] = useState(null);
  const [error, setError] = useState(null);
  const [seenAt, setSeenAt] = useState(() => Date.now());
  const sessionRef = useRef(null);

  const apply = useCallback(
    (next) => {
      // A different customer must never see the previous one's cached conversations.
      if (sessionRef.current?.customer.id !== next?.customer.id) dispatch(baseApi.util.resetApiState());
      sessionRef.current = next;
      setSession(next);
      setError(null);
      if (next) dispatch(signedIn(asCustomer(next)));
    },
    [dispatch],
  );

  // API calls carry the widget session token; if the API stops accepting it (expired, data erased), start over.
  useEffect(() => {
    setTokenSource({
      getToken: async () => sessionRef.current?.token ?? null,
      unauthorized: () => {
        forgetSession(sessionRef.current);
        apply(null);
      },
    });
  }, [apply]);

  // Who is chatting: changes when the website signs the customer in or out.
  useEffect(() => {
    if (mock) {
      apply(demoUser && { kind: demoUser.visitor ? 'visitor' : 'identified', customer: { id: demoUser.sub, name: demoUser.name } });
      if (demoUser) dispatch(signedIn(demoUser));
      return undefined;
    }
    const held = storedSession(identity);
    apply(held); // null until a new session arrives, so nothing is fetched with the previous person's token
    if (held || !identity) return undefined; // a guest gets a session when they open the chat
    let current = true;
    sessionFor(identity).then(
      (next) => current && apply(next),
      (e) => current && setError(e.message),
    );
    return () => {
      current = false; // signed in or out again before this one arrived
    };
  }, [identity, demoUser, mock, apply, dispatch]);

  // Opening the chat as a new guest creates their session.
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const ensureSession = useCallback(() => {
    if (mock || sessionRef.current) return;
    const forIdentity = identity;
    sessionFor(forIdentity).then(
      (next) => identityRef.current === forIdentity && apply(next),
      (e) => identityRef.current === forIdentity && setError(e.message),
    );
  }, [mock, identity, apply]);

  useEffect(() => {
    if (open) ensureSession();
  }, [open, ensureSession, session]);

  // A reply that arrived while the chat was minimised shows as a dot on the launcher.
  const { data: conversations = [] } = useGetMyConversationsQuery(undefined, { skip: !session, pollingInterval: open ? 0 : 10_000 });
  const live = conversations.find(isOpen);
  const last = live?.lastMessage;
  const getToken = useCallback(() => sessionRef.current?.token ?? null, []);
  usePresence(live?.id, getToken); // "here" every 15 s while the page is open — panel open or minimised
  const unread = !open && Boolean(last && last.sender !== 'customer' && last.createdAt > seenAt);

  useEffect(() => {
    onState?.({ open, unread });
  }, [open, unread, onState]);

  const toggle = useCallback((next) => {
    setOpen(next);
    setSeenAt(Date.now());
  }, []);

  useEffect(() => {
    if (command) toggle(command.type === 'baton:open');
  }, [command, toggle]);

  return open ? (
    <WidgetPanel key={session?.customer.id ?? 'none'} session={session} error={error} onRetry={ensureSession} onClose={() => toggle(false)} />
  ) : (
    <Launcher unread={unread} onOpen={() => toggle(true)} />
  );
}
