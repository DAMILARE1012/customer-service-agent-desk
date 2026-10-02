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
  useGetInsightsQuery,
  useGetAgentsQuery,
  useUpdateAgentMutation,
  useGetAdminConversationsQuery,
  useGetPolicyQuery,
  useUpdatePolicyMutation,
  useResetPolicyMutation,
} = adminApi;
