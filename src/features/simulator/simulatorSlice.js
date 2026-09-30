import { createSlice } from '@reduxjs/toolkit';

const simulatorSlice = createSlice({
  name: 'simulator',
  initialState: { open: false, conversationId: null },
  reducers: {
    simulatorToggled(state) {
      state.open = !state.open;
    },
    simulatorConversationChanged(state, action) {
      state.conversationId = action.payload;
    },
  },
  selectors: {
    selectSimulatorOpen: (state) => state.open,
    selectSimulatorConversationId: (state) => state.conversationId,
  },
});

export const { simulatorToggled, simulatorConversationChanged } = simulatorSlice.actions;
export const { selectSimulatorOpen, selectSimulatorConversationId } = simulatorSlice.selectors;
export default simulatorSlice;
