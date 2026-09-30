import { baseApi, conversationTags } from '../../api/baseApi.js';

// Every transition in and out of the handoff state is an explicit, named endpoint.
export const handoffApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    acceptHandoff: build.mutation({
      query: ({ conversationId, agentId }) => ({
        url: `/conversations/${conversationId}/handoff/accept`,
        method: 'POST',
        body: { agentId },
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    takeOver: build.mutation({
      query: ({ conversationId, agentId }) => ({
        url: `/conversations/${conversationId}/takeover`,
        method: 'POST',
        body: { agentId },
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    returnToBot: build.mutation({
      query: ({ conversationId, agentId }) => ({
        url: `/conversations/${conversationId}/handoff/return`,
        method: 'POST',
        body: { agentId },
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    resolveConversation: build.mutation({
      query: ({ conversationId, agentId }) => ({
        url: `/conversations/${conversationId}/resolve`,
        method: 'POST',
        body: { agentId },
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
  }),
});

export const {
  useAcceptHandoffMutation,
  useTakeOverMutation,
  useReturnToBotMutation,
  useResolveConversationMutation,
} = handoffApi;
