import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// VITE_* variables are bundled into the browser. Refuse to start if one looks like a secret,
// e.g. VITE_GROQ_API_KEY — the Groq key must stay server-side as GROQ_API_KEY.
const SECRET_NAME = /KEY|SECRET|TOKEN|PASSWORD/i;

function assertNoClientSecrets(env) {
  const leaked = Object.keys(env).filter((name) => name.startsWith('VITE_') && SECRET_NAME.test(name));
  if (leaked.length) {
    throw new Error(
      `Refusing to expose ${leaked.join(', ')} to the browser. Drop the VITE_ prefix and read it on the server instead.`,
    );
  }
}

export default defineConfig(({ mode }) => {
  assertNoClientSecrets(loadEnv(mode, process.cwd(), 'VITE_'));
  return {
    plugins: [react(), tailwindcss()],
  };
});
