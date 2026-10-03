// npm run accounts — every login for this local stack, grouped by who uses it, with URLs and passwords:
// from Vault for the ones that live there (read with the local root token in infra/vault/local/init.txt),
// otherwise from .env. Staff usernames and roles come from the Keycloak realm file;
// customers never sign in to Baton.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const envFile = path.join(root, '.env');
if (!fs.existsSync(envFile)) {
  console.error('No .env yet: copy .env.example to .env and fill it in.');
  process.exit(1);
}
const env = Object.fromEntries(
  fs.readFileSync(envFile, 'utf8').split(/\r?\n/).filter((l) => /^[A-Z_][A-Z0-9_]*=/.test(l)).map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]),
);
const realm = JSON.parse(fs.readFileSync(path.join(root, 'infra/keycloak/import/baton-realm.json'), 'utf8'));
const people = realm.users.filter((u) => !u.serviceAccountClientId);
const withRole = (role, exclude = []) => people.filter((u) => u.realmRoles.includes(role) && !exclude.some((r) => u.realmRoles.includes(r)));

// Passwords kept in Vault (see infra/vault/init.sh). Local development only: uses the root token.
async function fromVault() {
  const init = path.join(root, 'infra/vault/local/init.txt');
  if (!env.VAULT_ADDR || !fs.existsSync(init)) return null;
  const token = fs.readFileSync(init, 'utf8').match(/Initial Root Token: (\S+)/)?.[1];
  try {
    const found = {};
    for (const path of ['keycloak', 'observability']) {
      const res = await fetch(`${env.VAULT_ADDR}/v1/secret/data/baton/${path}`, { headers: { 'X-Vault-Token': token } });
      if (res.ok) Object.assign(found, (await res.json()).data.data);
    }
    return found;
  } catch {
    return null; // Vault isn't running
  }
}
const vault = await fromVault();
const value = (key, fallback = '(not set)') =>
  env[key] || vault?.[key] || (env.VAULT_ADDR && !vault ? '(in Vault — start it with npm run infra:up)' : fallback);
const web = env.BATON_WEB_URL || 'http://localhost:5173';
const keycloak = env.KEYCLOAK_URL || 'http://localhost:8080';

const sections = [
  {
    title: 'Customers — no sign-in',
    url: `${web}/demo-store  (a pretend shop with the chat widget, bottom right)`,
    users: ['none. Guests chat anonymously; the shop’s demo bar "signs in" as a seeded customer'],
    password: '—',
  },
  {
    title: 'Staff app — agents',
    url: `${web}  (lands on /desk)`,
    users: withRole('agent', ['admin']).map((u) => u.username),
    password: value('BATON_DEMO_PASSWORD'),
  },
  {
    title: 'Staff app — admins',
    url: `${web}  (desk, plus /admin)`,
    users: withRole('admin').map((u) => `${u.username} (admin + agent)`),
    password: value('BATON_DEMO_PASSWORD'),
  },
  { title: 'Keycloak admin console — users, roles, sessions', url: `${keycloak}/admin`, users: [value('KEYCLOAK_ADMIN_USER', 'admin')], password: value('KEYCLOAK_ADMIN_PASSWORD') },
  { title: 'Langfuse — traces and evaluation', url: env.LANGFUSE_BASE_URL || 'http://localhost:3000', users: [value('LANGFUSE_INIT_USER_EMAIL')], password: value('LANGFUSE_INIT_USER_PASSWORD') },
  { title: 'Vault — the API’s secrets (sign in with method “Token”)', url: `http://localhost:${env.VAULT_PORT || 8200}`, users: ['root token'], password: 'in infra/vault/local/init.txt (keep it private)' },
  { title: 'Mailpit — every email the app sends (alerts, replies)', url: `http://localhost:${env.MAILPIT_UI_PORT || 8025}`, users: ['none'], password: '—' },
  { title: 'Grafana — monitoring', url: `http://localhost:${env.GRAFANA_PORT || 3001}`, users: [value('GRAFANA_ADMIN_USER', 'admin')], password: value('GRAFANA_ADMIN_PASSWORD') },
];

const bold = (s) => (process.stdout.isTTY ? `\x1b[1m${s}\x1b[0m` : s);
console.log(`\n${bold('Baton — sign-in accounts')} (from .env; keep this output private)\n`);
for (const s of sections) {
  console.log(bold(s.title));
  console.log(`  URL       ${s.url}`);
  console.log(`  Username  ${s.users.join(', ')}`);
  console.log(`  Password  ${s.password}\n`);
}
console.log('The demo password is set when Keycloak first imports the realm; after that, change passwords in the Keycloak admin console.');
console.log('Keycloak holds staff only: customers are identified by the website that embeds the widget.\n');
