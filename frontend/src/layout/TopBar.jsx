import { AgentStatus } from '../features/agent/components/AgentStatus.jsx';
import { AlertsToggle } from '../features/notifications/AlertsToggle.jsx';
import { AppHeader } from './AppHeader.jsx';
import { QueueStats } from './QueueStats.jsx';

/** The desk's header: live queue numbers, new-handoff alerts and the agent's availability. */
export function TopBar() {
  return (
    <AppHeader
      subtitle="Agent desk"
      center={<QueueStats />}
      right={
        <div className="flex items-center gap-2">
          <AlertsToggle />
          <AgentStatus />
        </div>
      }
    />
  );
}
