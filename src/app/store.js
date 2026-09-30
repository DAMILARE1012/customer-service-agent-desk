import { combineSlices, configureStore } from '@reduxjs/toolkit';
import { setupListeners } from '@reduxjs/toolkit/query';
import { baseApi } from '../api/baseApi.js';
import agentSlice from '../features/agent/agentSlice.js';
import composerSlice from '../features/composer/composerSlice.js';
import deskSlice from '../features/conversations/deskSlice.js';
import notificationsSlice from '../features/notifications/notificationsSlice.js';
import simulatorSlice from '../features/simulator/simulatorSlice.js';
import { listenerMiddleware } from './listeners.js';

const rootReducer = combineSlices(baseApi, agentSlice, deskSlice, composerSlice, simulatorSlice, notificationsSlice);

export const store = configureStore({
  reducer: rootReducer,
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().prepend(listenerMiddleware.middleware).concat(baseApi.middleware),
});

// Enables refetchOnFocus / refetchOnReconnect.
setupListeners(store.dispatch);
