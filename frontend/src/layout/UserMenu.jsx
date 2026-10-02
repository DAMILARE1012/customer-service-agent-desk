import { useEffect, useRef, useState } from 'react';
import { ROLE_LABEL } from '../auth/roles.js';
import { useSession } from '../auth/useSession.js';
import { Avatar, Icon } from '../components/ui/index.js';

/** Who's signed in, their roles, account settings and sign-out. */
export function UserMenu({ tone = 'dark' }) {
  const { user, mode, signOut, accountUrl } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => !ref.current?.contains(event.target) && setOpen(false);
    const onKey = (event) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (!user) return null;
  const dark = tone === 'dark';

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        className={`flex items-center gap-2 rounded-lg py-1 pr-1.5 pl-1 transition ${dark ? 'hover:bg-white/10' : 'hover:bg-slate-100'}`}
      >
        <Avatar name={user.name} size="sm" />
        <span className={`hidden text-xs font-medium sm:block ${dark ? 'text-slate-200' : 'text-slate-700'}`}>{user.name}</span>
        <Icon name="chevronDown" className={`size-3.5 ${dark ? 'text-slate-400' : 'text-slate-400'}`} />
      </button>

      {open && (
        <div role="menu" className="absolute right-0 z-50 mt-2 w-64 overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-slate-900/10">
          <div className="border-b border-slate-100 px-4 py-3">
            <p className="text-sm font-semibold text-slate-900">{user.name}</p>
            {user.email && <p className="truncate text-xs text-slate-500">{user.email}</p>}
            <p className="mt-1.5 flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <span key={role} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                  {ROLE_LABEL[role]}
                </span>
              ))}
            </p>
          </div>
          {accountUrl && (
            <a href={accountUrl} role="menuitem" className="flex items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50">
              <Icon name="lock" className="size-4 text-slate-400" />
              Account &amp; password
            </a>
          )}
          <button type="button" role="menuitem" onClick={signOut} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50">
            <Icon name="logout" className="size-4 text-slate-400" />
            {mode === 'demo' ? 'Switch demo user' : 'Sign out'}
          </button>
        </div>
      )}
    </div>
  );
}
