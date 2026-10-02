import { useSelector } from 'react-redux';
import { Link, usePath } from '../app/router.jsx';
import { selectUser } from '../auth/authSlice.js';
import { workspaceAt, workspacesFor } from '../auth/roles.js';
import { Brand } from '../components/brand/Brand.jsx';
import { Icon } from '../components/ui/index.js';
import { UserMenu } from './UserMenu.jsx';

/** Switch between the workspaces this person's roles allow (hidden when there's only one). */
function WorkspaceNav({ tone }) {
  const user = useSelector(selectUser);
  const current = workspaceAt(usePath());
  const workspaces = workspacesFor(user);
  if (workspaces.length < 2) return null;
  const dark = tone === 'dark';

  return (
    <nav className={`flex items-center gap-1 rounded-lg p-0.5 ${dark ? 'bg-white/5 ring-1 ring-white/10' : 'bg-slate-100'}`} aria-label="Workspaces">
      {workspaces.map((w) => {
        const active = w.id === current?.id;
        return (
          <Link
            key={w.id}
            to={w.path}
            aria-current={active ? 'page' : undefined}
            className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
              active ? (dark ? 'bg-white text-slate-900' : 'bg-white text-slate-900 shadow-sm') : dark ? 'text-slate-300 hover:text-white' : 'text-slate-500 hover:text-slate-900'
            }`}
          >
            <Icon name={w.icon} className="size-3.5" />
            {w.label}
          </Link>
        );
      })}
    </nav>
  );
}

/** Top bar shared by every workspace: brand, workspace switcher, page-specific content, user menu. */
export function AppHeader({ subtitle, center, right, tone = 'dark' }) {
  const dark = tone === 'dark';
  return (
    <header className={`flex h-14 shrink-0 items-center justify-between gap-4 px-4 sm:px-5 ${dark ? 'bg-slate-900' : 'border-b border-slate-200 bg-white'}`}>
      <div className="flex min-w-0 items-center gap-4">
        <Brand subtitle={subtitle} tone={tone} />
        <WorkspaceNav tone={tone} />
      </div>
      {center}
      <div className="flex items-center gap-3">
        {right}
        <UserMenu tone={tone} />
      </div>
    </header>
  );
}
