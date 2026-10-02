import { LIST_ID, TAG, baseApi } from '../../api/baseApi.js';

export const conversationsApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getConversations: build.query({
      query: () => '/conversations',
      providesTags: (result = []) => [
        ...result.map(({ id }) => ({ type: TAG.CONVERSATION, id })),
        { type: TAG.CONVERSATION, id: LIST_ID },
      ],
    }),
    getConversation: build.query({
      query: (id) => `/conversations/${id}`,
      providesTags: (result, error, id) => [{ type: TAG.CONVERSATION, id }],
    }),
  }),
});

export const { useGetConversationsQuery, useGetConversationQuery } = conversationsApi;
