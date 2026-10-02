import { TAG, baseApi } from '../../api/baseApi.js';

// Staff-only: a customer's past sessions in brief. Agents get the history; the bot never does.
export const customerApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getCustomerTimeline: build.query({
      query: (customerId) => `/customers/${customerId}/conversations`,
      providesTags: (result, error, customerId) => [{ type: TAG.CUSTOMER, id: customerId }],
    }),
  }),
});

export const { useGetCustomerTimelineQuery } = customerApi;
