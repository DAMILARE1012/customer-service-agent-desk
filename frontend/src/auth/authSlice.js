import { createSlice } from '@reduxjs/toolkit';
import { config } from '../config.js';

// 'keycloak': real sign-in. 'demo': persona picker against the mock backend.
export const AUTH_MODE = config.auth.keycloakUrl ? 'keycloak' : 'demo';

const authSlice = createSlice({
  name: 'auth',
  initialState: { status: 'loading', user: null, error: null }, // loading | signedIn | signedOut | error
  reducers: {
    signedIn(state, action) {
      Object.assign(state, { status: 'signedIn', user: action.payload, error: null });
    },
    signedOut(state) {
      Object.assign(state, { status: 'signedOut', user: null, error: null });
    },
    authFailed(state, action) {
      Object.assign(state, { status: 'error', user: null, error: action.payload });
    },
  },
  selectors: {
    selectAuthStatus: (state) => state.status,
    selectUser: (state) => state.user,
    selectAuthError: (state) => state.error,
  },
});

export const { signedIn, signedOut, authFailed } = authSlice.actions;
export const { selectAuthStatus, selectUser, selectAuthError } = authSlice.selectors;
export default authSlice;
