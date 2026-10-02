import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { getAccessToken, keycloakLogin } from '../auth/keycloak.js';
import { config } from '../config.js';
import { mockBaseQuery } from './mock/mockBaseQuery.js';

// Where the bearer token comes from: staff sign in with Keycloak; the customer chat widget holds a widget
// session token instead (features/widget sets this). Mock backend: the signed-in persona is the user.
let tokenSource = {
  getToken: getAccessToken,
  unauthorized: () => config.auth.keycloakUrl && keycloakLogin(), // session ended: back to sign-in
};

export function setTokenSource(source) {
  tokenSource = source;
}

// Point VITE_API_URL at the real backend and every endpoint switches over — nothing else changes.
const rawBaseQuery = config.api.baseUrl
  ? fetchBaseQuery({
      baseUrl: config.api.baseUrl,
      prepareHeaders: async (headers) => {
        const token = await tokenSource.getToken();
        if (token) headers.set('Authorization', `Bearer ${token}`);
        return headers;
      },
    })
  : mockBaseQuery({ latency: config.api.mockLatencyMs });

async function baseQuery(args, api, extraOptions) {
  const result = await rawBaseQuery(args, api, extraOptions);
  if (result.error?.status === 401) tokenSource.unauthorized();
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
  REVIEW: 'Review',
  AUDIT: 'Audit',
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
