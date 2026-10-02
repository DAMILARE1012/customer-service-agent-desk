import { createSelector } from '@reduxjs/toolkit';
import { TAG, baseApi } from '../../api/baseApi.js';

// GET /me: the signed-in user plus their customer / agent / admin profile rows from the app database.
export const accountApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getMe: build.query({
      query: () => '/me',
      providesTags: [TAG.ME],
    }),
  }),
});

export const { useGetMeQuery } = accountApi;

const NO_AGENT = Object.freeze({ id: null, name: '', capacity: 0, active: false });
const selectMeResult = accountApi.endpoints.getMe.select();

/** The signed-in agent's profile (capacity, active) — a placeholder until /me has loaded. */
export const selectCurrentAgent = createSelector(selectMeResult, (result) => result.data?.agent ?? NO_AGENT);
export const selectCurrentCustomer = createSelector(selectMeResult, (result) => result.data?.customer ?? null);
