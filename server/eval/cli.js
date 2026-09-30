import fs from 'node:fs/promises';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { config } from '../config.js';
import { createRetriever } from '../rag/retriever.js';
import { QUESTION_SETS, loadQuestions } from './datasets.js';
import {
  contextPrecisionAtK,
  firstRelevantRank,
  mean,
  ndcgAtK,
  noMatchThreshold,
  precisionAtK,
  precisionThreshold,
  recallAtK,
  retrievalMetrics,
  summarize,
} from './metrics.js';
import { OFF_TOPIC_QUESTIONS } from './offTopicQuestions.js';

const { values } = parseArgs({ options: { set: { type: 'string', default: 'expert' } } });
const setNames = values.set === 'all' ? Object.keys(QUESTION_SETS) : [values.set];
const MODES = ['dense', 'keyword', 'hybrid'];
const SEARCH = { topK: 10, sources: ['wixqa'], audience: 'customer' };

const pct = (x) => (x == null ? '   —' : `${(x * 100).toFixed(0).padStart(3)}%`);
const num = (x) => (x == null ? '  —  ' : x.toFixed(3));
const ceil2 = (x) => Math.ceil(x * 100) / 100;
const floor2 = (x) => Math.floor(x * 100) / 100;

const retriever = await createRetriever();
const wixqa = retriever.manifest.sources.wixqa;
if (!wixqa) {
  console.error('The index has no WixQA articles. Add "wixqa" to INGEST_SOURCES and run `npm run ingest`.');
  process.exit(1);
}
if (wixqa.limit) console.warn(`⚠ The index was built with --limit=${wixqa.limit}; most correct articles are missing, so scores will be low.\n`);

const questions = (await Promise.all(setNames.map(loadQuestions))).flat();
console.log(`Evaluating ${questions.length} questions (${setNames.join(' + ')}) and ${OFF_TOPIC_QUESTIONS.length} off-topic questions against ${wixqa.documents} WixQA articles…\n`);

// ── Retrieval quality per mode ───────────────────────────────────────────────
const byMode = {};
for (const mode of MODES) {
  const rows = [];
  for (const { question, articleIds } of questions) {
    const { confidence, results } = await retriever.search(question, { ...SEARCH, mode });
    rows.push({
      confidence,
      rank: firstRelevantRank(results, articleIds),
      recall5: recallAtK(results, articleIds, 5),
      precision5: precisionAtK(results, articleIds, 5),
      ndcg5: ndcgAtK(results, articleIds, 5),
      contextPrecision5: contextPrecisionAtK(results, articleIds, 5),
    });
  }
  const graded = Object.fromEntries(['recall5', 'precision5', 'ndcg5', 'contextPrecision5'].map((key) => [key, mean(rows.map((r) => r[key]))]));
  byMode[mode] = { metrics: { ...retrievalMetrics(rows.map((r) => r.rank)), ...graded }, rows };
}

console.log('Retrieval (article level; hit@k = any correct article in the top k)');
console.log('  mode       hit@1  hit@3  hit@10  Recall@5  Precision@5  nDCG@5  CtxPrecision@5    MRR');
for (const mode of MODES) {
  const m = byMode[mode].metrics;
  console.log(
    `  ${mode.padEnd(9)} ${pct(m.hit1)}   ${pct(m.hit3)}   ${pct(m.hit10)}     ${pct(m.recall5)}        ${pct(m.precision5)}   ${m.ndcg5.toFixed(3)}          ${m.contextPrecision5.toFixed(3)}  ${m.mrr.toFixed(3)}`,
  );
}
console.log('  (Precision@5 is capped near 26%: questions average 1.3 correct articles, so most of any top 5 cannot be relevant.)');

// ── Confidence calibration (hybrid, the mode the bot uses) ───────────────────
const positives = byMode.hybrid.rows.map((r) => ({ confidence: r.confidence, correct: r.rank !== null && r.rank <= 3 }));
const negatives = [];
for (const question of OFF_TOPIC_QUESTIONS) {
  const { confidence } = await retriever.search(question, { ...SEARCH, mode: 'hybrid' });
  negatives.push({ confidence });
}

const distributions = {
  'real, right article in top 3': summarize(positives.filter((p) => p.correct).map((p) => p.confidence)),
  'real, right article missed': summarize(positives.filter((p) => !p.correct).map((p) => p.confidence)),
  'off-topic': summarize(negatives.map((n) => n.confidence)),
};
console.log('\nConfidence (cosine similarity of the top result)');
console.log('                                   p5     p25  median    p95     max    n');
for (const [label, d] of Object.entries(distributions)) {
  if (!d) continue;
  console.log(`  ${label.padEnd(30)} ${num(d.p5)}  ${num(d.p25)}  ${num(d.median)}  ${num(d.p95)}  ${num(d.max)}  ${String(d.n).padStart(3)}`);
}

// ── Suggested thresholds ─────────────────────────────────────────────────────
const answer = precisionThreshold(positives, negatives, config.eval.answerPrecision);
const copilot = precisionThreshold(positives, negatives, config.eval.copilotPrecision);
const noMatch = noMatchThreshold(positives, negatives, config.eval.noMatchMaxMissRate);

const suggestions = {
  answerThreshold: answer && ceil2(answer.threshold),
  copilotThreshold: copilot && ceil2(copilot.threshold),
  noMatchThreshold: floor2(noMatch.threshold),
};

console.log(`\nSuggested handoff thresholds  (${retriever.manifest.embedding.signature}, hybrid retrieval)`);
if (answer) {
  console.log(`  answer    ≥ ${suggestions.answerThreshold.toFixed(2)}   bot answers ${pct(answer.answeredShare).trim()} of real questions on its own; ${pct(answer.precision).trim()} of those have the right article in the top 3 (target ${pct(config.eval.answerPrecision).trim()}); ${pct(answer.offTopicAbove).trim()} of off-topic slip through`);
} else console.log(`  answer    —      no threshold reaches ${pct(config.eval.answerPrecision).trim()} precision; lower EVAL_ANSWER_PRECISION or improve retrieval`);
if (copilot) {
  console.log(`  copilot   ≥ ${suggestions.copilotThreshold.toFixed(2)}   drafts for ${pct(copilot.answeredShare).trim()} of real questions; ${pct(copilot.precision).trim()} grounded in the right article (target ${pct(config.eval.copilotPrecision).trim()})`);
} else console.log(`  copilot   —      no threshold reaches ${pct(config.eval.copilotPrecision).trim()} precision`);
console.log(`  no match  < ${suggestions.noMatchThreshold.toFixed(2)}   ${pct(noMatch.realBelow).trim()} of real questions fall below (limit ${pct(config.eval.noMatchMaxMissRate).trim()}); catches ${pct(noMatch.offTopicBelow).trim()} of off-topic questions`);

if (suggestions.answerThreshold != null && suggestions.noMatchThreshold > suggestions.answerThreshold) {
  console.log('  ⚠ "no match" sits above "answer": real and off-topic scores overlap heavily for this model/corpus.');
}
console.log('\nThese replace the demo keyword-score thresholds once the backend serves answers from this index.');

// ── Save ─────────────────────────────────────────────────────────────────────
const report = {
  createdAt: new Date().toISOString(),
  sets: setNames,
  questions: questions.length,
  offTopicQuestions: OFF_TOPIC_QUESTIONS.length,
  index: { signature: retriever.manifest.embedding.signature, chunks: retriever.size, builtAt: retriever.manifest.builtAt, chunking: retriever.manifest.chunking },
  retrieval: Object.fromEntries(MODES.map((m) => [m, byMode[m].metrics])),
  confidence: distributions,
  targets: config.eval,
  thresholds: { suggestions, answer, copilot, noMatch },
};
await fs.mkdir(config.paths.eval, { recursive: true });
const file = path.join(config.paths.eval, `report-${setNames.join('+')}-${report.createdAt.replace(/[:.]/g, '-')}.json`);
await fs.writeFile(file, JSON.stringify(report, null, 2));
await fs.writeFile(path.join(config.paths.eval, 'latest.json'), JSON.stringify(report, null, 2));
console.log(`Report saved to ${path.relative(config.paths.root, file)}`);
