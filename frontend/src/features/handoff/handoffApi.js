import { baseApi, conversationTags } from '../../api/baseApi.js';

// Every transition in and out of the handoff state is an explicit, named endpoint. The acting agent
// is whoever the access token says — there's no agentId to send (or spoof).
export const handoffApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    acceptHandoff: build.mutation({
      query: ({ conversationId }) => ({
        url: `/conversations/${conversationId}/handoff/accept`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    takeOver: build.mutation({
      query: ({ conversationId }) => ({
        url: `/conversations/${conversationId}/takeover`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    returnToBot: build.mutation({
      query: ({ conversationId }) => ({
        url: `/conversations/${conversationId}/handoff/return`,
        method: 'POST',
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
    resolveConversation: build.mutation({
      query: ({ conversationId }) => ({
        url: `/conversations/${conversationId}/resolve`,
        method: 'POST',
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
