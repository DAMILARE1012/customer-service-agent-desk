import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import { config } from '../config.js';
import { mockBaseQuery } from './mock/mockBaseQuery.js';

// Point VITE_API_URL at a real backend and every endpoint switches over — nothing else changes.
const baseQuery = config.api.baseUrl
  ? fetchBaseQuery({ baseUrl: config.api.baseUrl })
  : mockBaseQuery({ latency: config.api.mockLatencyMs });

export const TAG = {
  CONVERSATION: 'Conversation',
  CUSTOMER: 'Customer',
};

export const LIST_ID = 'LIST';

/** Tags to invalidate after any mutation that changes a single conversation. */
export const conversationTags = (id) => [
  { type: TAG.CONVERSATION, id },
  { type: TAG.CONVERSATION, id: LIST_ID },
];

// Feature slices inject their own endpoints (see features/*/api).
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery,
  tagTypes: Object.values(TAG),
  endpoints: () => ({}),
});
