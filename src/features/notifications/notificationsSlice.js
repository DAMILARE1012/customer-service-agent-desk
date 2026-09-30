import { createSlice, nanoid } from '@reduxjs/toolkit';

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState: { items: [] },
  reducers: {
    notificationAdded: {
      reducer(state, action) {
        state.items.push(action.payload);
      },
      prepare: (notification) => ({ payload: { id: nanoid(), createdAt: Date.now(), ...notification } }),
    },
    notificationDismissed(state, action) {
      state.items = state.items.filter((n) => n.id !== action.payload);
    },
  },
  selectors: {
    selectNotifications: (state) => state.items,
  },
});

export const { notificationAdded, notificationDismissed } = notificationsSlice.actions;
export const { selectNotifications } = notificationsSlice.selectors;
export default notificationsSlice;
