// npm start — the whole of Baton with one command.
//
//   npm start                      infrastructure + observability in Docker, then the API and the web app from
//                                  source in this terminal (live reload); Ctrl+C stops those two
//   npm start -- --docker          everything as containers, then returns (stop with: npm stop)
//   npm start -- --no-obs          skip Langfuse and Grafana (they take ~3 minutes and ~3 GB to start)
//
// Order (each step waits for the one before): Vault → its setup (unseal, secrets) → Postgres, Keycloak, Mailpit
// → observability → API → web. First run: creates .env from .env.example and installs what's missing.
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = new Set(process.argv.slice(2));
const docker = args.has('--docker');
const withObs = !args.has('--no-obs');
const isWindows = process.platform === 'win32';
const tty = process.stdout.isTTY;
const paint = (code) => (text) => (tty ? `\x1b[${code}m${text}\x1b[0m` : text);
const [bold, dim, green, yellow, red, cyan, magenta] = ['1', '2', '32', '33', '31', '36', '35'].map(paint);

const step = (text) => console.log(`\n${bold('▸')} ${text}`);
const fail = (text) => {
  console.error(`\n${red('✗')} ${text}`);
  process.exit(1);
};

function run(command, commandArgs, { cwd = root, quiet = false } = {}) {
  const result = spawnSync(command, commandArgs, { cwd, stdio: quiet ? 'pipe' : 'inherit', shell: isWindows });
  return result.status === 0;
}

const compose = (file, extra = []) => ['compose', '--env-file', '.env', '-f', file, ...extra];

async function isUp(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(2000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function waitFor(url, label, seconds) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (await isUp(url)) return true;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  fail(`${label} didn't come up within ${seconds}s (${url}). Check its output above.`);
}

// ── 0. Prerequisites ────────────────────────────────────────────────────────
if (!run('docker', ['info'], { quiet: true })) fail('Docker isn’t running. Start Docker Desktop and try again.');

const envFile = path.join(root, '.env');
if (!fs.existsSync(envFile)) {
  fs.copyFileSync(path.join(root, '.env.example'), envFile);
  console.log(`${yellow('!')} Created .env from .env.example. Every secret is generated into Vault on first start —`);
  console.log('  except GROQ_API_KEY: set it in .env before this first start (or later in the Vault UI) for the bot to answer.');
}
const env = Object.fromEntries(
  fs.readFileSync(envFile, 'utf8').split(/\r?\n/).filter((l) => /^[A-Z_][A-Z0-9_]*=/.test(l)).map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]),
);

// ── 1. Infrastructure: Vault first, then everything that needs a secret ─────
step('Infrastructure — Vault (unseal + secrets), Postgres, Keycloak, Mailpit');
if (!run('docker', compose('infra/docker-compose.yml', [...(docker ? ['--profile', 'app'] : []), 'up', '-d', '--wait', ...(docker ? ['--build'] : [])])))
  fail('The infrastructure didn’t start. Run `npm run infra:logs` to see why.');

// The API run from source reaches Vault, Postgres and Keycloak through ports published on this machine.
// Docker Desktop's port forwarding sometimes stops answering for a container that was restarted under it
// (the container itself is fine — "healthy" inside Docker). Restarting the container gives it a fresh mapping;
// data stays in its volume. Vault comes back sealed, so its setup runs again to unseal it.
const vaultUp = async () => {
  try {
    const response = await fetch('http://127.0.0.1:8200/v1/sys/health', { signal: AbortSignal.timeout(3000) });
    return response.status === 200; // 200 = initialised, unsealed, active
  } catch {
    return false;
  }
};
const postgresUp = (port) =>
  new Promise((resolve) => {
    // Postgres answers an SSLRequest with one byte ('S' or 'N'); a broken forward accepts and says nothing.
    const socket = net.connect({ host: '127.0.0.1', port }, () => socket.write(Buffer.from([0, 0, 0, 8, 4, 210, 22, 47])));
    const done = (ok) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(3000, () => done(false));
    socket.once('data', (data) => done(data.length > 0));
    socket.once('error', () => done(false));
    socket.once('close', () => done(false)); // a broken forward may accept and then just hang up
  });
const reachability = [
  ['vault', 'Vault', vaultUp, ['up', 'vault-init']],
  ['db', 'Postgres', () => postgresUp(Number(env.BATON_DB_PORT || 5433)), null],
  ['keycloak', 'Keycloak', () => isUp(`http://127.0.0.1:${env.KEYCLOAK_PORT || 8080}/realms/baton`), null],
];
for (const [service, label, check, after] of reachability) {
  if (service === 'vault' && !env.VAULT_ADDR) continue;
  if (await check()) continue;
  console.log(`${yellow('!')} ${label} is running but not answering on its port here — restarting it to repair Docker’s port forwarding`);
  run('docker', compose('infra/docker-compose.yml', ['restart', service]));
  run('docker', compose('infra/docker-compose.yml', ['up', '-d', '--wait', service]));
  if (after) run('docker', compose('infra/docker-compose.yml', after));
  if (!(await check())) fail(`${label} still isn’t reachable from this machine. Restart Docker Desktop, then run npm start again.`);
}

// ── 2. Observability (depends on Vault) ─────────────────────────────────────
if (withObs) {
  step('Observability — Langfuse, Prometheus, Grafana (first start takes a few minutes)');
  if (!run('docker', compose('observability/docker-compose.yml', ['up', '-d', '--wait'])))
    fail('The observability stack didn’t start. Run `npm run obs:logs` — or start without it: npm start -- --no-obs');
}

const urls = [
  ['Staff app (agents, admin)', 'http://localhost:5173'],
  ['Demo shop with the chat widget', 'http://localhost:5173/demo-store'],
  ['API docs', 'http://localhost:8787/docs'],
  ['Keycloak admin', 'http://localhost:8080/admin'],
  ['Vault', 'http://localhost:8200'],
  ['Mailpit (emails)', 'http://localhost:8025'],
  ...(withObs ? [['Langfuse', 'http://localhost:3000'], ['Grafana', 'http://localhost:3001']] : []),
];

function banner() {
  console.log(`\n${green('✓')} ${bold('Baton is running')}\n`);
  for (const [label, url] of urls) console.log(`  ${label.padEnd(32)} ${cyan(url)}`);
  console.log(`\n  Logins: ${bold('npm run accounts')}   ·   Stop: ${docker ? bold('npm stop') : `${bold('Ctrl+C')} (API + web), then ${bold('npm stop')} (containers)`}\n`);
}

// ── 3a. Everything in Docker ─────────────────────────────────────────────────
if (docker) {
  const indexed = run('docker', ['run', '--rm', '-v', 'baton_baton_data:/data', 'alpine:3.22', 'test', '-s', '/data/index/manifest.json'], { quiet: true });
  if (!indexed) console.log(`\n${yellow('!')} The knowledge index isn’t built yet, so the bot can’t answer: run ${bold('npm run app:ingest')} once (about an hour).`);
  await waitFor('http://127.0.0.1:8787/health', 'The API', 300);
  banner();
  process.exit(0);
}

// ── 3b. API and web app from source, in this terminal ────────────────────────
if (!fs.existsSync(path.join(root, 'frontend/node_modules'))) {
  step('Installing the web app’s dependencies');
  if (!run('npm', ['install', '--prefix', 'frontend'])) fail('npm install failed.');
}
if (!fs.existsSync(path.join(root, 'data/index/manifest.json')))
  console.log(`\n${yellow('!')} The knowledge index isn’t built yet, so the bot can’t answer: run ${bold('npm run ingest')} once (about an hour, resumable).`);
if (!env.GROQ_API_KEY && !env.VAULT_ADDR) console.log(`${yellow('!')} GROQ_API_KEY is empty: the bot will hand every question to a person.`);

const children = [];
function start(label, color, command, commandArgs, cwd) {
  const child = spawn(command, commandArgs, { cwd, shell: isWindows, env: { ...process.env, FORCE_COLOR: '1', PYTHONUNBUFFERED: '1' } });
  const prefix = color(`[${label}]`.padEnd(6));
  for (const stream of [child.stdout, child.stderr]) {
    let pending = '';
    stream.on('data', (chunk) => {
      const lines = (pending + chunk.toString()).split(/\r?\n/);
      pending = lines.pop();
      for (const line of lines) if (line.trim()) console.log(`${prefix} ${line}`);
    });
  }
  child.on('exit', (code) => {
    if (!stopping) {
      console.log(`${prefix} ${red(`stopped (exit ${code})`)}`);
      shutdown(code ?? 1);
    }
  });
  children.push(child);
}

let stopping = false;
function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  console.log(dim('\nStopping the API and the web app… (the containers keep running — npm stop stops them)'));
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (isWindows) spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    else child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 500);
}
process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

step('API and web app (from source, live reload)');
if (await isUp('http://127.0.0.1:8787/health')) console.log(dim('  An API is already running on :8787 — using it.'));
else start('api', magenta, 'uv', ['run', 'baton-api'], path.join(root, 'backend'));
if (await isUp('http://localhost:5173')) console.log(dim('  A web app is already running on :5173 — using it.'));
else start('web', cyan, 'npm', ['--prefix', 'frontend', 'run', 'dev', '--', '--strictPort'], root);

await waitFor('http://127.0.0.1:8787/health', 'The API', 300); // loading the embedding model takes a little while
await waitFor('http://localhost:5173', 'The web app', 120);
banner();
if (!children.length) process.exit(0);
