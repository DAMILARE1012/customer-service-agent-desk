import { createSelector } from '@reduxjs/toolkit';
import { CONVERSATION_STATUS } from '../../constants/conversation.js';
import { PRIORITY_META } from '../../constants/handoff.js';
import { QUEUE_VIEW } from '../../constants/queue.js';
import { selectCurrentAgent } from '../agent/agentSlice.js';
import { conversationsApi } from './conversationsApi.js';
import { selectQueueView, selectSearch } from './deskSlice.js';

const EMPTY = [];
const selectConversationsResult = conversationsApi.endpoints.getConversations.select();
export const selectAllConversations = createSelector(selectConversationsResult, (result) => result.data ?? EMPTY);

const VIEW_FILTERS = {
  [QUEUE_VIEW.NEEDS_AGENT]: (c) => c.status === CONVERSATION_STATUS.HANDOFF_PENDING,
  [QUEUE_VIEW.MINE]: (c, agentId) => c.status === CONVERSATION_STATUS.AGENT_ACTIVE && c.assignee?.id === agentId,
  [QUEUE_VIEW.BOT_LIVE]: (c) => c.status === CONVERSATION_STATUS.BOT_ACTIVE,
  [QUEUE_VIEW.ALL]: () => true,
};

// Handoffs: most urgent first, then longest-waiting. Everything else: most recent activity first.
const byPriorityThenWait = (a, b) =>
  PRIORITY_META[a.handoff.priority].rank - PRIORITY_META[b.handoff.priority].rank ||
  a.handoff.requestedAt - b.handoff.requestedAt;
const byRecent = (a, b) => b.updatedAt - a.updatedAt;

export const selectQueueCounts = createSelector([selectAllConversations, selectCurrentAgent], (list, agent) =>
  Object.fromEntries(
    Object.entries(VIEW_FILTERS).map(([view, predicate]) => [view, list.filter((c) => predicate(c, agent.id)).length]),
  ),
);

export const selectMyActiveCount = createSelector(selectQueueCounts, (counts) => counts[QUEUE_VIEW.MINE]);

export const selectVisibleConversations = createSelector(
  [selectAllConversations, selectQueueView, selectSearch, selectCurrentAgent],
  (list, view, search, agent) => {
    const term = search.trim().toLowerCase();
    const filtered = list.filter(
      (c) =>
        VIEW_FILTERS[view](c, agent.id) &&
        (!term || c.customer.name.toLowerCase().includes(term) || c.subject?.toLowerCase().includes(term)),
    );
    return filtered.sort(view === QUEUE_VIEW.NEEDS_AGENT ? byPriorityThenWait : byRecent);
  },
);
