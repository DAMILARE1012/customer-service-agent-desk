import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { config } from '../config.js';
import { deskStats } from '../conversation/store.js';
import { httpDuration, httpRequests, registerStateGauges, registry } from '../observability/metrics.js';
import { initTracing, shutdownTracing } from '../observability/tracing.js';
import { getRetriever } from '../rag/answerer.js';
import { matchRoute } from './routes.js';

const tracing = initTracing();

const MAX_BODY_BYTES = 1_000_000;

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(Object.assign(new Error('Request body too large.'), { status: 413 }));
        req.destroy();
      } else chunks.push(chunk);
    });
    req.on('end', () => {
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(Object.assign(new Error('Body is not valid JSON.'), { status: 400 }));
      }
    });
    req.on('error', reject);
  });
}

function send(res, status, body, contentType = 'application/json') {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Access-Control-Allow-Origin': config.server.corsOrigin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}

// Index freshness for the gauges, read from disk (ingestion runs as a separate process).
let indexCache = { at: 0, value: { chunks: 0, builtAt: null, checkedAt: {} } };
function readIndexState() {
  if (Date.now() - indexCache.at < 15_000) return indexCache.value;
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(config.paths.index, 'manifest.json'), 'utf8'));
    const checkedAt = Object.fromEntries(Object.entries(manifest.sources ?? {}).map(([id, s]) => [id, s.checkedAt]));
    indexCache = { at: Date.now(), value: { chunks: manifest.count - (manifest.duplicates ?? 0), builtAt: manifest.builtAt, checkedAt } };
  } catch {
    indexCache = { at: Date.now(), value: { chunks: 0, builtAt: null, checkedAt: {} } };
  }
  return indexCache.value;
}
registerStateGauges(() => deskStats(), readIndexState);

async function handle(req, res) {
  const { pathname } = new URL(req.url, 'http://localhost');
  if (req.method === 'OPTIONS') return send(res, 204, '');

  if (req.method === 'GET' && pathname === '/metrics') {
    return send(res, 200, await registry.metrics(), registry.contentType);
  }
  if (req.method === 'GET' && pathname === '/health') {
    return send(res, 200, { ok: true, llmConfigured: Boolean(config.llm.apiKey), tracing, index: readIndexState() });
  }

  const route = matchRoute(req.method, pathname);
  const labels = { method: req.method, route: route?.name ?? 'unmatched' };
  const endTimer = httpDuration.startTimer(labels);
  let status = 200;
  try {
    if (!route) {
      status = 404;
      return send(res, status, { message: `No route for ${req.method} ${pathname}` });
    }
    const body = req.method === 'POST' ? await readJson(req) : undefined;
    const result = await route.handler(route.params, body);
    return send(res, status, result);
  } catch (error) {
    status = error.status ?? 500;
    if (status >= 500) console.error(`[api] ${req.method} ${pathname}`, error);
    return send(res, status, { message: status >= 500 ? 'Internal server error' : error.message });
  } finally {
    endTimer();
    httpRequests.inc({ ...labels, status: String(status) });
  }
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((error) => {
    console.error('[api] unhandled', error);
    if (!res.headersSent) send(res, 500, { message: 'Internal server error' });
  });
});

console.log('Loading knowledge index and embedding model…');
const retriever = await getRetriever();
server.listen(config.server.port, () => {
  console.log(`Support API on http://localhost:${config.server.port}  ·  ${retriever.size} chunks  ·  model ${config.llm.model}`);
  console.log(`  LLM: ${config.llm.apiKey ? 'configured' : 'GROQ_API_KEY missing — the bot will hand every question to an agent'}`);
  console.log(`  Tracing: ${tracing ? `Langfuse at ${config.observability.langfuseBaseUrl}` : 'off (set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY)'}`);
  console.log(`  Metrics: http://localhost:${config.server.port}/metrics`);
});

async function shutdown(signal) {
  console.log(`\n${signal} received — flushing traces…`);
  server.close();
  await shutdownTracing().catch(() => {});
  process.exit(0);
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
