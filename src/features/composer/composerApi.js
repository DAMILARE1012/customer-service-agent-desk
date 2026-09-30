import { baseApi, conversationTags } from '../../api/baseApi.js';
import { conversationsApi } from '../conversations/conversationsApi.js';
import { SENDER } from '../../constants/conversation.js';

export const composerApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    sendAgentMessage: build.mutation({
      query: ({ conversationId, agent, text }) => ({
        url: `/conversations/${conversationId}/agent-messages`,
        method: 'POST',
        body: { agentId: agent.id, text },
      }),
      // Optimistic: show the reply instantly, roll back if the server rejects it.
      async onQueryStarted({ conversationId, agent, text }, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          conversationsApi.util.updateQueryData('getConversation', conversationId, (draft) => {
            draft.messages.push({
              id: `optimistic_${Date.now()}`,
              sender: SENDER.AGENT,
              text,
              createdAt: Date.now(),
              author: { id: agent.id, name: agent.name },
              pending: true,
            });
            draft.copilot = null;
          }),
        );
        try {
          await queryFulfilled;
        } catch {
          patch.undo();
        }
      },
      invalidatesTags: (result, error, { conversationId }) => conversationTags(conversationId),
    }),
  }),
});

export const { useSendAgentMessageMutation } = composerApi;
