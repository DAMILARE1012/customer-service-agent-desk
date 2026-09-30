import { createSlice } from '@reduxjs/toolkit';

// The signed-in agent. In a real app this would come from auth.
const initialState = {
  current: { id: 'agt_alex', name: 'Alex Rivera', capacity: 3 },
  availability: 'online', // 'online' | 'away'
};

const agentSlice = createSlice({
  name: 'agent',
  initialState,
  reducers: {
    availabilityToggled(state) {
      state.availability = state.availability === 'online' ? 'away' : 'online';
    },
  },
  selectors: {
    selectCurrentAgent: (state) => state.current,
    selectAvailability: (state) => state.availability,
  },
});

export const { availabilityToggled } = agentSlice.actions;
export const { selectCurrentAgent, selectAvailability } = agentSlice.selectors;
export default agentSlice;
