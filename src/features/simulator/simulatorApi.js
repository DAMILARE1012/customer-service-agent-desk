import { LIST_ID, TAG, baseApi, conversationTags } from '../../api/baseApi.js';

// The simulator plays the customer's side of the widget so the desk can be exercised end to end.
export const simulatorApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCustomers: build.query({
      query: () => '/customers',
      providesTags: [{ type: TAG.CUSTOMER, id: LIST_ID }],
    }),
    startConversation: build.mutation({
      query: ({ customerId }) => ({ url: '/conversations', method: 'POST', body: { customerId } }),
      invalidatesTags: [{ type: TAG.CONVERSATION, id: LIST_ID }],
    }),
    sendCustomerMessage: build.mutation({
      query: ({ conversationId, text }) => ({
        url: `/conversations/${conversationId}/customer-messages`,
        method: 'POST',
        body: { text },
      }),
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
  }),
});

export const { useGetCustomersQuery, useStartConversationMutation, useSendCustomerMessageMutation } = simulatorApi;
