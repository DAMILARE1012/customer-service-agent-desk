import { createSlice } from '@reduxjs/toolkit';

// Desk-local presence. Who the agent is (and their capacity) comes from /me — see account/accountApi.js.
const agentSlice = createSlice({
  name: 'agent',
  initialState: { availability: 'online' }, // 'online' | 'away'
  reducers: {
    availabilityToggled(state) {
      state.availability = state.availability === 'online' ? 'away' : 'online';
    },
  },
  selectors: {
    selectAvailability: (state) => state.availability,
  },
});

export const { availabilityToggled } = agentSlice.actions;
export const { selectAvailability } = agentSlice.selectors;
export default agentSlice;
