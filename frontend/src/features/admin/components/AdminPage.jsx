import { Link, pathSegments, usePath } from '../../../app/router.jsx';
import { Icon } from '../../../components/ui/index.js';
import { AppHeader } from '../../../layout/AppHeader.jsx';
import { AgentsView } from './AgentsView.jsx';
import { ConversationsView } from './ConversationsView.jsx';
import { InsightsView } from './InsightsView.jsx';
import { PolicyView } from './PolicyView.jsx';

const SECTIONS = [
  { id: '', label: 'Overview', icon: 'chart', View: InsightsView, description: 'How the assistant and the desk are doing.' },
  { id: 'agents', label: 'Agents', icon: 'users', View: AgentsView, description: 'Who can take handoffs, and how many at once.' },
  { id: 'conversations', label: 'Conversations', icon: 'chat', View: ConversationsView, description: 'Every conversation, across all agents.' },
  { id: 'policy', label: 'Handoff policy', icon: 'sliders', View: PolicyView, description: 'When the assistant steps aside. Changes apply to the next message.' },
];

/** Admin workspace: /admin, /admin/agents, /admin/conversations, /admin/policy. */
export function AdminPage() {
  const [sectionId = ''] = pathSegments(usePath(), '/admin');
  const section = SECTIONS.find((s) => s.id === sectionId) ?? SECTIONS[0];
  const { View } = section;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-50">
      <AppHeader subtitle="Admin" />
      <div className="flex min-h-0 flex-1">
        <nav className="hidden w-56 shrink-0 border-r border-slate-200 bg-white p-3 md:block" aria-label="Admin sections">
          <ul className="space-y-0.5">
            {SECTIONS.map((s) => {
              const active = s.id === section.id;
              return (
                <li key={s.id}>
                  <Link
                    to={s.id ? `/admin/${s.id}` : '/admin'}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${active ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'}`}
                  >
                    <Icon name={s.icon} className="size-4" />
                    {s.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-8">
            <header>
              <h1 className="text-xl font-semibold tracking-tight text-slate-900">{section.label}</h1>
              <p className="mt-1 text-sm text-slate-500">{section.description}</p>
              {/* Section switcher for narrow screens */}
              <div className="mt-3 flex gap-1 overflow-x-auto md:hidden">
                {SECTIONS.map((s) => (
                  <Link key={s.id} to={s.id ? `/admin/${s.id}` : '/admin'} className={`rounded-full px-3 py-1 text-xs font-medium whitespace-nowrap ${s.id === section.id ? 'bg-indigo-600 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>
                    {s.label}
                  </Link>
                ))}
              </div>
            </header>
            <View />
          </div>
        </main>
      </div>
    </div>
  );
}
