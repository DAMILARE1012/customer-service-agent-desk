import { useSyncExternalStore } from 'react';

// A deliberately tiny router: Baton has three workspaces (/chat, /desk, /admin) and a few sub-pages,
// so the History API plus one hook covers it without a routing dependency.

const listeners = new Set();

function subscribe(listener) {
  listeners.add(listener);
  window.addEventListener('popstate', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('popstate', listener);
  };
}

export function navigate(path, { replace = false } = {}) {
  if (path === window.location.pathname) return;
  window.history[replace ? 'replaceState' : 'pushState'](null, '', path);
  listeners.forEach((listener) => listener());
}

export const usePath = () => useSyncExternalStore(subscribe, () => window.location.pathname);

/** `/chat/conv_1` with base `/chat` → ['conv_1']. */
export const pathSegments = (path, base) =>
  path
    .slice(base.length)
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent);

/** An <a> that navigates in-app (modifier-clicks still open a new tab). */
export function Link({ to, onClick, ...props }) {
  const handleClick = (event) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return <a href={to} onClick={handleClick} {...props} />;
}
