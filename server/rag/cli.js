import { parseArgs } from 'node:util';
import { createRetriever } from './retriever.js';

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    audience: { type: 'string', default: 'customer' },
    mode: { type: 'string', default: 'hybrid' },
    k: { type: 'string', default: '5' },
  },
});

const query = positionals.join(' ').trim();
if (!query) {
  console.log('Usage: npm run search -- "how do I connect my domain?" [--audience=customer|agent|any] [--mode=hybrid|dense|keyword] [--k=5]');
  process.exit(1);
}

const retriever = await createRetriever();
const started = Date.now();
const { confidence, results } = await retriever.search(query, { audience: values.audience, mode: values.mode, topK: Number(values.k) });

console.log(`\n"${query}"  ·  ${values.mode}, ${values.audience}  ·  confidence ${confidence.toFixed(3)}  ·  ${Date.now() - started} ms over ${retriever.size} chunks\n`);
results.forEach((r, i) => {
  const section = r.headingPath.length ? ` › ${r.headingPath.join(' › ')}` : '';
  const shared = r.alsoIn.length ? `  (+ same text in ${r.alsoIn.length} other articles)` : '';
  console.log(`${i + 1}. [${r.similarity.toFixed(3)} · bm25 ${r.keywordScore}] ${r.title}${section}${shared}`);
  console.log(`   ${r.source} · ${r.url}`);
  console.log(`   ${r.text.replace(/\s+/g, ' ').slice(0, 200)}…\n`);
});
