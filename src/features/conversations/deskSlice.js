import { createSlice } from '@reduxjs/toolkit';
import { QUEUE_VIEW } from '../../constants/queue.js';

// UI state for the desk itself (what's selected / filtered). Server data lives in RTK Query.
const initialState = {
  selectedConversationId: null,
  queueView: QUEUE_VIEW.NEEDS_AGENT,
  search: '',
  contextTab: 'handoff', // 'handoff' | 'knowledge' | 'customer'
};

const deskSlice = createSlice({
  name: 'desk',
  initialState,
  reducers: {
    conversationSelected(state, action) {
      state.selectedConversationId = action.payload;
    },
    queueViewChanged(state, action) {
      state.queueView = action.payload;
    },
    searchChanged(state, action) {
      state.search = action.payload;
    },
    contextTabChanged(state, action) {
      state.contextTab = action.payload;
    },
  },
  selectors: {
    selectSelectedConversationId: (state) => state.selectedConversationId,
    selectQueueView: (state) => state.queueView,
    selectSearch: (state) => state.search,
    selectContextTab: (state) => state.contextTab,
  },
});

export const { conversationSelected, queueViewChanged, searchChanged, contextTabChanged } = deskSlice.actions;
export const { selectSelectedConversationId, selectQueueView, selectSearch, selectContextTab } = deskSlice.selectors;
export default deskSlice;
