import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { config } from '../../config.js';
import { AUTH_MODE, authFailed, selectAuthError, selectAuthStatus, selectUser, signedIn, signedOut } from '../authSlice.js';
import { loadDemoPersona } from '../demoPersonas.js';
import { initKeycloak } from '../keycloak.js';
import { DemoSignIn } from './DemoSignIn.jsx';
import { FullScreenMessage } from './FullScreenMessage.jsx';

/** Nothing renders until we know who the user is: Keycloak sign-in, or the demo persona picker. */
export function AuthGate({ children }) {
  const dispatch = useDispatch();
  const status = useSelector(selectAuthStatus);
  const error = useSelector(selectAuthError);
  const user = useSelector(selectUser);

  useEffect(() => {
    if (AUTH_MODE === 'demo') {
      if (config.api.baseUrl) {
        dispatch(authFailed('VITE_API_URL points at the real API, which needs Keycloak sign-in — set VITE_KEYCLOAK_URL in .env.'));
        return;
      }
      const persona = loadDemoPersona();
      dispatch(persona ? signedIn(persona.user) : signedOut());
      return;
    }
    initKeycloak()
      .then((user) => dispatch(signedIn(user)))
      .catch((e) => dispatch(authFailed(`Couldn’t reach sign-in at ${config.auth.keycloakUrl}. Is Keycloak running (npm run infra:up)? ${e?.message ?? ''}`)));
  }, [dispatch]);

  // Coming from the demo shop, the store still holds the widget's customer for a moment: wait for the staff persona.
  const customerFromWidget = AUTH_MODE === 'demo' && status === 'signedIn' && user?.roles.length === 1 && user.roles[0] === 'customer';
  if (status === 'loading' || customerFromWidget) return <FullScreenMessage title="Signing you in…" busy />;
  if (status === 'error') {
    return (
      <FullScreenMessage title="Sign-in isn’t available" description={error}>
        <button type="button" onClick={() => window.location.reload()} className="text-sm font-medium text-indigo-600 hover:text-indigo-500">
          Try again
        </button>
      </FullScreenMessage>
    );
  }
  if (status === 'signedOut') return <DemoSignIn />;
  return children;
}
