import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// One .env at the project root configures the frontend and the backend.
const envDir = fileURLToPath(new URL('..', import.meta.url));

// VITE_* variables are bundled into the browser. Refuse to start if one looks like a secret,
// e.g. VITE_GROQ_API_KEY — the Groq key must stay server-side as GROQ_API_KEY.
// Whole name segments, so VITE_GROQ_API_KEY is refused but VITE_KEYCLOAK_URL is fine.
const SECRET_NAME = /(^|_)(KEY|APIKEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE|CREDENTIALS?)(_|$)/i;

function assertNoClientSecrets(env) {
  const leaked = Object.keys(env).filter((name) => name.startsWith('VITE_') && SECRET_NAME.test(name));
  if (leaked.length) {
    throw new Error(
      `Refusing to expose ${leaked.join(', ')} to the browser. Drop the VITE_ prefix and read it on the server instead.`,
    );
  }
}

export default defineConfig(({ mode }) => {
  assertNoClientSecrets(loadEnv(mode, envDir, 'VITE_'));
  return {
    envDir,
    plugins: [react(), tailwindcss()],
  };
});
