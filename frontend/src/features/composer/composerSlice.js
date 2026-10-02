import { createSlice } from '@reduxjs/toolkit';

// Drafts are kept per conversation so switching chats never loses a half-written reply.
const composerSlice = createSlice({
  name: 'composer',
  initialState: { drafts: {} },
  reducers: {
    draftChanged(state, action) {
      const { conversationId, text } = action.payload;
      state.drafts[conversationId] = text;
    },
    draftCleared(state, action) {
      delete state.drafts[action.payload];
    },
  },
  selectors: {
    selectDraft: (state, conversationId) => state.drafts[conversationId] ?? '',
  },
});

export const { draftChanged, draftCleared } = composerSlice.actions;
export const { selectDraft } = composerSlice.selectors;
export default composerSlice;
