import { useGetMeQuery } from '../features/account/accountApi.js';
import { QueuePanel } from '../features/conversations/components/QueuePanel.jsx';
import { ContextPanel } from '../features/handoff/components/ContextPanel.jsx';
import { Toaster } from '../features/notifications/components/Toaster.jsx';
import { ConversationPanel } from '../features/thread/components/ConversationPanel.jsx';
import { TopBar } from './TopBar.jsx';

// Three-pane desk: queue │ conversation │ handoff context.
export function DeskLayout() {
  useGetMeQuery(); // the signed-in agent's profile: id, capacity, active
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <TopBar />
      <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)] lg:grid-cols-[280px_minmax(0,1fr)_340px] xl:grid-cols-[320px_minmax(0,1fr)_380px]">
        <QueuePanel />
        <ConversationPanel />
        <div className="hidden min-h-0 lg:flex lg:flex-col">
          <ContextPanel />
        </div>
      </div>
      <Toaster />
    </div>
  );
}
