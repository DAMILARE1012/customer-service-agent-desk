import { handleRequest } from './routes.js';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Drop-in replacement for `fetchBaseQuery`: same args (`string | { url, method, body }`),
 * same `{ data } | { error: { status, data } }` result — so endpoints don't know it's a mock.
 */
export const mockBaseQuery =
  ({ latency = [150, 450] } = {}) =>
  async (args) => {
    const request = typeof args === 'string' ? { url: args } : args;
    const [min, max] = latency;
    await wait(min + Math.random() * (max - min));

    try {
      // Clone so the store (which freezes state) never shares references with the mock DB.
      return { data: structuredClone(handleRequest(request)) };
    } catch (error) {
      return { error: { status: error.status ?? 500, data: { message: error.message } } };
    }
  };
