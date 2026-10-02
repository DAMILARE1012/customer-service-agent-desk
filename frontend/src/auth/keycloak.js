import Keycloak from 'keycloak-js';
import { config } from '../config.js';
import { ROLE } from './roles.js';

// Authorization code flow with PKCE against the `baton-web` public client. Tokens live in memory only
// (never localStorage); keycloak-js refreshes them before they expire.

let keycloak = null;
let initializing = null;

const APP_ROLES = new Set(Object.values(ROLE));

export const userFromToken = (token) => ({
  sub: token.sub,
  username: token.preferred_username,
  name: token.name || token.preferred_username,
  email: token.email ?? null,
  roles: (token.realm_access?.roles ?? []).filter((role) => APP_ROLES.has(role)),
});

/** Sign in (redirecting to Keycloak if needed) and resolve with the user. Safe to call twice (StrictMode). */
export function initKeycloak() {
  initializing ??= (async () => {
    keycloak = new Keycloak({ url: config.auth.keycloakUrl, realm: config.auth.realm, clientId: config.auth.clientId });
    await keycloak.init({ onLoad: 'login-required', pkceMethod: 'S256', checkLoginIframe: false });
    // Expired while the tab slept: try a refresh, otherwise go back to the login page.
    keycloak.onTokenExpired = () => keycloak.updateToken(30).catch(() => keycloak.login());
    return userFromToken(keycloak.tokenParsed);
  })();
  return initializing;
}

/** A fresh access token for API calls (refreshed when it has under 30 s left). */
export async function getAccessToken() {
  if (!keycloak?.authenticated) return null;
  try {
    await keycloak.updateToken(30);
  } catch {
    keycloak.login();
    return null;
  }
  return keycloak.token;
}

export const keycloakLogin = () => keycloak?.login();
export const keycloakLogout = () => keycloak?.logout({ redirectUri: window.location.origin });
export const keycloakAccountUrl = () => keycloak?.createAccountUrl();
