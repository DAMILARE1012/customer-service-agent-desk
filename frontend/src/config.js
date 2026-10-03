// Single entry point for client-side configuration. Values come from `.env` (see `.env.example`).
//
// Only variables prefixed with VITE_ reach the browser bundle. Secrets such as GROQ_API_KEY are
// deliberately left unprefixed so Vite never ships them to the client.
//
// In the Docker image the same VITE_* names are read when the container starts and written to
// /config.js (window.__BATON_CONFIG__), so one image works for anyone's URLs; they override build-time values.

const env = { ...(import.meta.env ?? {}), ...(globalThis.__BATON_CONFIG__ ?? {}) }; // import.meta.env is undefined outside Vite

function number(name, fallback, { min = -Infinity, max = Infinity } = {}) {
  const raw = env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  if (Number.isNaN(value) || value < min || value > max) {
    console.warn(`[config] ${name}="${raw}" is invalid (expected ${min}–${max}); using ${fallback}.`);
    return fallback;
  }
  return value;
}

const string = (name, fallback = '') => env[name]?.trim() || fallback;

export const config = {
  auth: {
    // Empty → no Keycloak: a demo persona picker signs you in (mock backend only).
    keycloakUrl: string('VITE_KEYCLOAK_URL'),
    realm: string('VITE_KEYCLOAK_REALM', 'baton'),
    clientId: string('VITE_KEYCLOAK_CLIENT_ID', 'baton-web'),
  },

  api: {
    // Empty → the in-browser mock backend is used.
    baseUrl: string('VITE_API_URL'),
    pollingIntervalMs: number('VITE_POLLING_INTERVAL_MS', 4000, { min: 1000 }),
    mockLatencyMs: [number('VITE_MOCK_LATENCY_MIN_MS', 150, { min: 0 }), number('VITE_MOCK_LATENCY_MAX_MS', 450, { min: 0 })],
  },

  handoffPolicy: {
    answerThreshold: number('VITE_HANDOFF_ANSWER_THRESHOLD', 0.5, { min: 0, max: 1 }),
    noMatchThreshold: number('VITE_HANDOFF_NO_MATCH_THRESHOLD', 0.25, { min: 0, max: 1 }),
    minTermsForNoMatch: number('VITE_HANDOFF_MIN_TERMS_FOR_NO_MATCH', 4, { min: 1 }),
    maxFailedAttempts: number('VITE_HANDOFF_MAX_FAILED_ATTEMPTS', 2, { min: 1 }),
    sentimentThreshold: number('VITE_HANDOFF_SENTIMENT_THRESHOLD', -0.5, { min: -1, max: 1 }),
    copilotThreshold: number('VITE_HANDOFF_COPILOT_THRESHOLD', 0.45, { min: 0, max: 1 }),
  },

  sla: {
    warnAfterMs: number('VITE_HANDOFF_SLA_WARN_SECONDS', 120, { min: 1 }) * 1000,
    breachAfterMs: number('VITE_HANDOFF_SLA_BREACH_SECONDS', 300, { min: 1 }) * 1000,
  },
};
