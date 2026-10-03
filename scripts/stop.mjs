// npm stop — stop Baton's containers (observability, the app containers, then the infrastructure).
// Data is kept in Docker volumes. The API and web app started by `npm start` stop with Ctrl+C in that terminal.
// Next start: Vault comes back sealed, and `npm start` (or `npm run infra:up`) unseals it again.
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const shell = process.platform === 'win32';
const down = (file, extra = []) =>
  spawnSync('docker', ['compose', '--env-file', '.env', '-f', file, ...extra, 'down'], { cwd: root, stdio: 'inherit', shell }).status === 0;

const ok = [down('observability/docker-compose.yml'), down('infra/docker-compose.yml', ['--profile', 'app'])].every(Boolean);
console.log(ok ? '\n✓ Stopped. Your data is kept; `npm start` brings everything back.' : '\n✗ Something didn’t stop cleanly — see above.');
process.exit(ok ? 0 : 1);
