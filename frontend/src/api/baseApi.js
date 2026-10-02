import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { getAccessToken, keycloakLogin } from '../auth/keycloak.js';
import { config } from '../config.js';
import { mockBaseQuery } from './mock/mockBaseQuery.js';

// Point VITE_API_URL at the real backend and every endpoint switches over — nothing else changes.
// Real backend: each request carries a fresh Keycloak access token. Mock: the demo persona is the user.
const rawBaseQuery = config.api.baseUrl
  ? fetchBaseQuery({
      baseUrl: config.api.baseUrl,
      prepareHeaders: async (headers) => {
        const token = await getAccessToken();
        if (token) headers.set('Authorization', `Bearer ${token}`);
        return headers;
      },
    })
  : mockBaseQuery({ latency: config.api.mockLatencyMs });

async function baseQuery(args, api, extraOptions) {
  const result = await rawBaseQuery(args, api, extraOptions);
  // The session ended (revoked, expired while offline): back to the sign-in page.
  if (result.error?.status === 401 && config.auth.keycloakUrl) keycloakLogin();
  return result;
}

export const TAG = {
  ME: 'Me',
  CONVERSATION: 'Conversation',
  MY_CONVERSATION: 'MyConversation',
  CUSTOMER: 'Customer',
  AGENT: 'Agent',
  POLICY: 'Policy',
  INSIGHTS: 'Insights',
};

export const LIST_ID = 'LIST';

/** Tags to invalidate after any mutation that changes a single conversation. */
export const conversationTags = (id) => [
  { type: TAG.CONVERSATION, id },
  { type: TAG.CONVERSATION, id: LIST_ID },
  { type: TAG.INSIGHTS, id: LIST_ID },
];

// Feature slices inject their own endpoints (see features/*/api).
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery,
  tagTypes: Object.values(TAG),
  endpoints: () => ({}),
});
