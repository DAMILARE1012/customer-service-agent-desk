import { AgentStatus } from '../features/agent/components/AgentStatus.jsx';
import { AppHeader } from './AppHeader.jsx';
import { QueueStats } from './QueueStats.jsx';

/** The desk's header: live queue numbers and the agent's availability. */
export function TopBar() {
  return <AppHeader subtitle="Agent desk" center={<QueueStats />} right={<AgentStatus />} />;
}
