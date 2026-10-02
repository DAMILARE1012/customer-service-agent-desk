import { LIST_ID, TAG, baseApi } from '../../api/baseApi.js';

// Admin-only endpoints (/admin/*). The API refuses them without the admin role.
export const adminApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getInsights: build.query({
      query: () => '/admin/insights',
      providesTags: [{ type: TAG.INSIGHTS, id: LIST_ID }],
    }),
    getAgents: build.query({
      query: () => '/admin/agents',
      providesTags: (result = []) => [...result.map(({ id }) => ({ type: TAG.AGENT, id })), { type: TAG.AGENT, id: LIST_ID }],
    }),
    updateAgent: build.mutation({
      query: ({ id, ...changes }) => ({ url: `/admin/agents/${id}`, method: 'PATCH', body: changes }),
      // Optimistic: toggles and steppers feel instant; rolled back if the API refuses.
      async onQueryStarted({ id, ...changes }, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          adminApi.util.updateQueryData('getAgents', undefined, (draft) => {
            Object.assign(draft.find((a) => a.id === id) ?? {}, changes);
          }),
        );
        try {
          await queryFulfilled;
        } catch {
          patch.undo();
        }
      },
      invalidatesTags: (result, error, { id }) => [{ type: TAG.AGENT, id }, TAG.ME],
    }),
    getAdminConversations: build.query({
      query: (params = {}) => ({ url: '/admin/conversations', params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)) }),
      providesTags: [{ type: TAG.CONVERSATION, id: LIST_ID }],
    }),
    getCustomersAdmin: build.query({
      query: () => '/admin/customers',
      providesTags: [{ type: TAG.CUSTOMER, id: LIST_ID }],
    }),
    eraseCustomer: build.mutation({
      query: (customerId) => ({ url: `/admin/customers/${customerId}/erase`, method: 'POST', body: { confirm: customerId } }),
      invalidatesTags: [{ type: TAG.CUSTOMER, id: LIST_ID }, { type: TAG.CONVERSATION, id: LIST_ID }, { type: TAG.INSIGHTS, id: LIST_ID }, TAG.AUDIT],
    }),
    getReviewItems: build.query({
      query: (params = {}) => ({ url: '/admin/review', params }),
      providesTags: [TAG.REVIEW],
    }),
    runReview: build.mutation({
      query: () => ({ url: '/admin/review/run', method: 'POST' }),
      invalidatesTags: [TAG.REVIEW, TAG.AUDIT],
    }),
    updateReviewItem: build.mutation({
      query: ({ id, ...changes }) => ({ url: `/admin/review/${id}`, method: 'PATCH', body: changes }),
      invalidatesTags: [TAG.REVIEW],
    }),
    reviewAction: build.mutation({
      // action: publish | approve | reject
      query: ({ id, action }) => ({ url: `/admin/review/${id}/${action}`, method: 'POST' }),
      invalidatesTags: [TAG.REVIEW, TAG.AUDIT],
    }),
    reindexKnowledge: build.mutation({
      query: () => ({ url: '/admin/knowledge/reindex', method: 'POST' }),
      invalidatesTags: [TAG.AUDIT],
    }),
    getAudit: build.query({
      query: (params = {}) => ({ url: '/admin/audit', params: Object.fromEntries(Object.entries(params).filter(([, v]) => v)) }),
      providesTags: [TAG.AUDIT],
    }),
    getPolicy: build.query({
      query: () => '/admin/policy',
      providesTags: [TAG.POLICY],
    }),
    updatePolicy: build.mutation({
      query: (values) => ({ url: '/admin/policy', method: 'PUT', body: values }),
      invalidatesTags: [TAG.POLICY],
    }),
    resetPolicy: build.mutation({
      query: () => ({ url: '/admin/policy/reset', method: 'POST' }),
      invalidatesTags: [TAG.POLICY],
    }),
  }),
});

export const {
  useGetCustomersAdminQuery,
  useEraseCustomerMutation,
  useGetReviewItemsQuery,
  useRunReviewMutation,
  useUpdateReviewItemMutation,
  useReviewActionMutation,
  useReindexKnowledgeMutation,
  useGetAuditQuery,
  useGetInsightsQuery,
  useGetAgentsQuery,
  useUpdateAgentMutation,
  useGetAdminConversationsQuery,
  useGetPolicyQuery,
  useUpdatePolicyMutation,
  useResetPolicyMutation,
} = adminApi;
