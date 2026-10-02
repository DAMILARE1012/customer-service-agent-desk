import { LIST_ID, TAG, baseApi } from '../../api/baseApi.js';
import { SENDER } from '../../constants/conversation.js';

// The customer's side: their own conversations only, in the customer-safe shape (no handoff brief).
export const chatApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getMyConversations: build.query({
      query: () => '/me/conversations',
      providesTags: (result = []) => [...result.map(({ id }) => ({ type: TAG.MY_CONVERSATION, id })), { type: TAG.MY_CONVERSATION, id: LIST_ID }],
    }),
    getMyConversation: build.query({
      query: (id) => `/me/conversations/${id}`,
      providesTags: (result, error, id) => [{ type: TAG.MY_CONVERSATION, id }],
    }),
    startConversation: build.mutation({
      query: () => ({ url: '/me/conversations', method: 'POST' }),
      async onQueryStarted(_, { dispatch, queryFulfilled }) {
        const { data } = await queryFulfilled;
        // Seed the cache so the first message can be shown optimistically right away.
        dispatch(chatApi.util.upsertQueryData('getMyConversation', data.id, data));
      },
      invalidatesTags: [{ type: TAG.MY_CONVERSATION, id: LIST_ID }],
    }),
    sendMessage: build.mutation({
      query: ({ conversationId, text }) => ({ url: `/me/conversations/${conversationId}/messages`, method: 'POST', body: { text } }),
      // Show the customer's message instantly; replace with the server's view (incl. the reply) when it lands.
      async onQueryStarted({ conversationId, text }, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          chatApi.util.updateQueryData('getMyConversation', conversationId, (draft) => {
            draft.messages.push({ id: `optimistic_${Date.now()}`, sender: SENDER.CUSTOMER, text, createdAt: Date.now(), pending: true });
          }),
        );
        try {
          const { data } = await queryFulfilled;
          dispatch(chatApi.util.upsertQueryData('getMyConversation', conversationId, data));
        } catch {
          patch.undo();
        }
      },
      invalidatesTags: [{ type: TAG.MY_CONVERSATION, id: LIST_ID }],
    }),
  }),
});

export const { useGetMyConversationsQuery, useGetMyConversationQuery, useStartConversationMutation, useSendMessageMutation } = chatApi;
