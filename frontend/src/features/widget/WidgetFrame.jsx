import { useCallback, useEffect, useState } from 'react';
import { WidgetApp } from './WidgetApp.jsx';

// The page inside the widget's iframe (/widget). The website loads /widget.js, which creates the iframe
// and talks to it with postMessage:
//   website → widget   baton:identify { token } · baton:logout · baton:open · baton:close
//   widget → website   baton:ready · baton:state { open, unread } (the embed script sizes the iframe)
// Nothing sensitive crosses: identity tokens are verified by the API, and the state carries no content.

export function WidgetFrame() {
  const [identity, setIdentity] = useState(null);
  const [command, setCommand] = useState(null);

  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    const onMessage = (event) => {
      if (event.source !== window.parent || !event.data?.type?.startsWith('baton:')) return;
      const { type, token } = event.data;
      if (type === 'baton:identify') setIdentity(typeof token === 'string' && token ? token : null);
      if (type === 'baton:logout') setIdentity(null);
      if (type === 'baton:open' || type === 'baton:close') setCommand({ type, at: Date.now() });
    };
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ type: 'baton:ready' }, '*');
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const onState = useCallback((state) => window.parent.postMessage({ type: 'baton:state', ...state }, '*'), []);

  return (
    <div className="flex h-screen w-screen items-end justify-end p-2">
      <WidgetApp identity={identity} onState={onState} command={command} />
    </div>
  );
}
