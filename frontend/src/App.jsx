import { useEffect } from 'react';
import { useSelector } from 'react-redux';
import { Link, navigate, usePath } from './app/router.jsx';
import { selectUser } from './auth/authSlice.js';
import { AuthGate } from './auth/components/AuthGate.jsx';
import { FullScreenMessage } from './auth/components/FullScreenMessage.jsx';
import { homePathFor, workspaceAt } from './auth/roles.js';
import { useSession } from './auth/useSession.js';
import { AdminPage } from './features/admin/components/AdminPage.jsx';
import { ChatPage } from './features/chat/components/ChatPage.jsx';
import { DeskLayout } from './layout/DeskLayout.jsx';

const PAGES = { chat: ChatPage, desk: DeskLayout, admin: AdminPage };

/** Route to the workspace for this path — if the signed-in roles allow it. */
function Workspaces() {
  const user = useSelector(selectUser);
  const path = usePath();
  const { signOut } = useSession();
  const workspace = workspaceAt(path);
  const home = homePathFor(user);

  useEffect(() => {
    if (!workspace && home !== '/no-access') navigate(home, { replace: true });
  }, [workspace, home]);

  if (home === '/no-access') {
    return (
      <FullScreenMessage title="Your account has no Baton role yet" description="Ask an admin to give you the customer, agent or admin role in Keycloak, then sign in again.">
        <button type="button" onClick={signOut} className="text-sm font-medium text-indigo-600 hover:text-indigo-500">Sign out</button>
      </FullScreenMessage>
    );
  }
  if (!workspace) return null;
  if (!workspace.allows(user)) {
    return (
      <FullScreenMessage title={`${workspace.label} isn’t available to you`} description="Your roles don’t include this workspace.">
        <Link to={home} className="text-sm font-medium text-indigo-600 hover:text-indigo-500">Go to your workspace →</Link>
      </FullScreenMessage>
    );
  }
  const Page = PAGES[workspace.id];
  return <Page />;
}

export default function App() {
  return (
    <AuthGate>
      <Workspaces />
    </AuthGate>
  );
}
