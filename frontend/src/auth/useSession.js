import { useDispatch, useSelector } from 'react-redux';
import { baseApi } from '../api/baseApi.js';
import { navigate } from '../app/router.jsx';
import { AUTH_MODE, selectUser, signedOut } from './authSlice.js';
import { saveDemoPersona } from './demoPersonas.js';
import { keycloakAccountUrl, keycloakLogout } from './keycloak.js';

/** The signed-in user and how to leave. */
export function useSession() {
  const dispatch = useDispatch();
  const user = useSelector(selectUser);

  const signOut = () => {
    if (AUTH_MODE === 'keycloak') {
      keycloakLogout(); // ends the Keycloak session and comes back to the sign-in page
      return;
    }
    saveDemoPersona(null);
    dispatch(baseApi.util.resetApiState());
    dispatch(signedOut());
    navigate('/', { replace: true }); // the next person lands on their own workspace
  };

  return { user, mode: AUTH_MODE, signOut, accountUrl: AUTH_MODE === 'keycloak' ? keycloakAccountUrl() : null };
}
