import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { config } from '../config.js';
import { getLangfuse, initTracing, shutdownTracing } from '../observability/tracing.js';
import { answerQuestion } from '../rag/answerer.js';
import { loadQuestions } from './datasets.js';
import { judge } from './judge.js';
import { contextPrecisionAtK, mean, ndcgAtK, recallAtK } from './metrics.js';
import { OFF_TOPIC_QUESTIONS } from './offTopicQuestions.js';

// End-to-end evaluation as a Langfuse experiment. Every question runs through the production answer
// step (retrieve → gate → generate with citations) and is scored on four layers:
//
//   retrieval   recall@5, nDCG@5, context precision@5          deterministic, from WixQA article labels
//   context     context recall                                  LLM judge: are the reference answer's facts in the context?
//   generation  faithfulness, answer relevance, correctness,    LLM judge (gpt-oss-120b)
//               citation correctness                            deterministic: does a citation come from a correct article?
//   decision    answered (WixQA), handoff correct (off-topic)   deterministic
//
// Results appear in Langfuse under Datasets → <dataset> → Runs, with a trace per question.

const HELP = `Usage: npm run eval:rag -- [options]

  --limit=N         WixQA questions to run (default EVAL_RAG_LIMIT=${config.eval.ragLimit}); off-topic added at N/5
  --name=TEXT       Run name shown in Langfuse (default: model + settings + time)
  --no-judge        Skip the LLM judge (retrieval and decision metrics only)
  --concurrency=N   Parallel questions (default EVAL_RAG_CONCURRENCY=${config.eval.ragConcurrency})`;

const { values } = parseArgs({
  options: {
    limit: { type: 'string' },
    name: { type: 'string' },
    'no-judge': { type: 'boolean', default: false },
    concurrency: { type: 'string' },
    help: { type: 'boolean', default: false },
  },
});
if (values.help) {
  console.log(HELP);
  process.exit(0);
}

const limit = Number(values.limit ?? config.eval.ragLimit);
const concurrency = Number(values.concurrency ?? config.eval.ragConcurrency);
const K = 5;
const hash = (text) => createHash('sha256').update(text).digest('hex').slice(0, 16);

if (!initTracing()) {
  console.error('Langfuse is not configured. Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY and start the stack with `npm run obs:up`.');
  process.exit(1);
}
const langfuse = getLangfuse();
const useJudge = !values['no-judge'] && Boolean(config.llm.apiKey);
if (!config.llm.apiKey) {
  console.warn('⚠ GROQ_API_KEY is empty: every answer will fail over to a handoff and the judge is off. Retrieval metrics are still measured.\n');
}

// ── 1. Dataset (idempotent upsert: stable ids from the question text) ──────────
const datasetName = config.eval.ragDataset;
async function syncDataset() {
  await langfuse.api.datasets
    .create({ name: datasetName, description: 'WixQA expert questions (answerable) + off-topic questions (should hand off)', metadata: { source: 'WixQA + hand-written off-topic set' } })
    .catch(() => {}); // already exists

  const expert = await loadQuestions('expert');
  const items = [
    ...expert.map(({ question, answer, articleIds }) => ({
      id: `wixqa-${hash(question)}`,
      input: { question },
      expectedOutput: { answer, articleIds, shouldAnswer: true },
      metadata: { kind: 'wixqa' },
    })),
    ...OFF_TOPIC_QUESTIONS.map((question) => ({
      id: `offtopic-${hash(question)}`,
      input: { question },
      expectedOutput: { shouldAnswer: false },
      metadata: { kind: 'off_topic' },
    })),
  ];
  for (let i = 0; i < items.length; i += 10) {
    await Promise.all(items.slice(i, i + 10).map((item) => langfuse.dataset.createItem({ datasetName, ...item })));
  }
  return items.length;
}

// ── 2. Task: the production answer step ───────────────────────────────────────
async function task({ input }) {
  const result = await answerQuestion({ question: input.question, purpose: 'eval' });
  const withArticles = (r) => ({ docId: r.docId, alsoIn: r.alsoIn.map((a) => a.docId), title: r.title });
  return {
    decision: result.status === 'answered' ? 'answered' : 'handed_off',
    status: result.status,
    answer: result.answer,
    confidence: result.retrieval.confidence,
    citations: result.citations.map(withArticles),
    contexts: result.retrieval.results.map((r) => ({ ...withArticles(r), text: r.text })),
    ...(result.error && { error: result.error }),
  };
}

// ── 3. Item evaluators ────────────────────────────────────────────────────────
async function evaluate({ input, output, expectedOutput, metadata }) {
  if (metadata?.kind === 'off_topic') {
    return [{ name: 'handoff_correct', value: output.decision === 'handed_off' ? 1 : 0, comment: `status: ${output.status}` }];
  }

  const gold = expectedOutput.articleIds;
  const evals = [
    { name: 'recall_at_5', value: recallAtK(output.contexts, gold, K) },
    { name: 'ndcg_at_5', value: ndcgAtK(output.contexts, gold, K) },
    { name: 'context_precision_at_5', value: contextPrecisionAtK(output.contexts, gold, K) },
    { name: 'answered', value: output.decision === 'answered' ? 1 : 0, comment: `status: ${output.status}` },
  ];
  if (output.decision === 'answered') {
    const goldSet = new Set(gold);
    const correct = output.citations.some((c) => goldSet.has(c.docId) || c.alsoIn.some((id) => goldSet.has(id)));
    evals.push({ name: 'citation_correct', value: correct ? 1 : 0, comment: output.citations.map((c) => c.title).join(' | ') });
  }

  if (useJudge) {
    try {
      const verdict = await judge({
        question: input.question,
        contexts: output.contexts.map((c) => c.text),
        answer: output.answer,
        reference: expectedOutput.answer,
      });
      const push = (name, value, comment) => value != null && evals.push({ name, value, comment });
      push('context_recall', verdict.contextRecall, verdict.reasoning);
      if (output.decision === 'answered') {
        push('faithfulness', verdict.faithfulness, verdict.unsupportedClaims.length ? `Unsupported: ${verdict.unsupportedClaims.join(' | ')}` : 'All claims supported');
        push('unsupported_claims', verdict.unsupportedClaims.length);
        push('answer_relevance', verdict.answerRelevance);
        push('answer_correctness', verdict.answerCorrectness, verdict.reasoning);
      }
    } catch (error) {
      evals.push({ name: 'judge_error', value: 1, comment: error.message });
    }
  }
  return evals;
}

// ── 4. Run-level summary ──────────────────────────────────────────────────────
const METRICS = [
  'recall_at_5',
  'ndcg_at_5',
  'context_precision_at_5',
  'context_recall',
  'answered',
  'citation_correct',
  'faithfulness',
  'answer_relevance',
  'answer_correctness',
  'unsupported_claims',
  'handoff_correct',
];

function summarize(itemResults) {
  const values = (name) => itemResults.flatMap((r) => r.evaluations).filter((e) => e.name === name).map((e) => e.value);
  const summary = Object.fromEntries(METRICS.map((name) => [name, { mean: mean(values(name)), n: values(name).length }]));
  // The number that matters most: of all answerable questions, how many got an answer that is right and grounded.
  const wixqa = itemResults.filter((r) => r.item.metadata?.kind === 'wixqa');
  const goodAnswers = wixqa.filter((r) => {
    const score = (name) => r.evaluations.find((e) => e.name === name)?.value;
    return score('answered') === 1 && (score('answer_correctness') ?? 0) >= 0.75 && (score('faithfulness') ?? 0) >= 0.9;
  }).length;
  summary.correct_and_grounded = { mean: wixqa.length && useJudge ? goodAnswers / wixqa.length : null, n: wixqa.length };
  return summary;
}

const runEvaluators = [
  async ({ itemResults }) =>
    Object.entries(summarize(itemResults))
      .filter(([, { mean: value }]) => value != null)
      .map(([name, { mean: value, n }]) => ({ name: `avg_${name}`, value, comment: `n=${n}` })),
];

// ── Run ───────────────────────────────────────────────────────────────────────
try {
  console.log(`Syncing dataset "${datasetName}"…`);
  const total = await syncDataset();
  const dataset = await langfuse.dataset.get(datasetName);
  const byKind = (kind) => dataset.items.filter((i) => i.metadata?.kind === kind && i.status !== 'ARCHIVED').sort((a, b) => a.id.localeCompare(b.id));
  const selected = [...byKind('wixqa').slice(0, limit), ...byKind('off_topic').slice(0, Math.max(1, Math.ceil(limit / 5)))];
  const kinds = selected.reduce((acc, i) => ({ ...acc, [i.metadata.kind]: (acc[i.metadata.kind] ?? 0) + 1 }), {});
  console.log(`Dataset has ${total} items; running ${selected.length} (${Object.entries(kinds).map(([k, n]) => `${n} ${k}`).join(', ')}) with concurrency ${concurrency}${useJudge ? `, judge ${config.judge.model}` : ', no judge'}…\n`);

  const runName = values.name ?? `${config.llm.model} · k=${config.policy.contextChunks} · no-match ${config.policy.noMatchThreshold} · ${new Date().toISOString().slice(0, 16)}`;
  const started = Date.now();
  const result = await langfuse.experiment.run({
    name: 'support-bot',
    runName,
    description: 'End-to-end RAG evaluation: retrieval, context, generation and handoff decision.',
    metadata: {
      answerModel: config.llm.model,
      judgeModel: useJudge ? config.judge.model : 'none',
      contextChunks: config.policy.contextChunks,
      noMatchThreshold: config.policy.noMatchThreshold,
      embedding: config.embedding.model,
    },
    data: selected,
    task,
    evaluators: [evaluate],
    runEvaluators,
    maxConcurrency: concurrency,
  });

  const summary = summarize(result.itemResults);
  const pct = (v) => (v == null ? '   —' : `${(v * 100).toFixed(0).padStart(3)}%`);
  const LABELS = {
    recall_at_5: ['Retrieval', 'Recall@5'],
    ndcg_at_5: ['Retrieval', 'nDCG@5'],
    context_precision_at_5: ['Retrieval', 'Context precision@5'],
    context_recall: ['Context', 'Context recall (judge)'],
    answered: ['Decision', 'Answered (answerable questions)'],
    handoff_correct: ['Decision', 'Handed off (off-topic questions)'],
    citation_correct: ['Generation', 'Citation from a correct article'],
    faithfulness: ['Generation', 'Faithfulness (judge)'],
    answer_relevance: ['Generation', 'Answer relevance (judge)'],
    answer_correctness: ['Generation', 'Answer correctness (judge)'],
    correct_and_grounded: ['End to end', 'Correct and grounded answers'],
  };
  console.log(`Run "${runName}" finished in ${((Date.now() - started) / 1000).toFixed(0)}s\n`);
  for (const [key, [layer, label]] of Object.entries(LABELS)) {
    const { mean: value, n } = summary[key];
    console.log(`  ${layer.padEnd(11)} ${label.padEnd(34)} ${pct(value)}   (n=${n})`);
  }
  if (summary.unsupported_claims.mean != null) console.log(`  ${'Generation'.padEnd(11)} ${'Unsupported claims per answer'.padEnd(34)} ${summary.unsupported_claims.mean.toFixed(2)}`);
  const errors = result.itemResults.filter((r) => r.output?.error).length;
  if (errors) console.log(`\n  ${errors} question(s) hit an LLM error while answering — see "status" in the traces.`);
  const judgeErrors = result.itemResults.flatMap((r) => r.evaluations).filter((e) => e.name === 'judge_error');
  if (judgeErrors.length) {
    console.log(`  ${judgeErrors.length} judgment(s) failed, so judge metrics cover fewer items. First error: ${judgeErrors[0].comment?.slice(0, 200)}`);
  }
  if (result.datasetRunUrl) console.log(`\nLangfuse run: ${result.datasetRunUrl}`);

  await fs.mkdir(config.paths.eval, { recursive: true });
  const file = path.join(config.paths.eval, `rag-${new Date().toISOString().replace(/[:.]/g, '-')}.json`);
  await fs.writeFile(file, JSON.stringify({ runName, datasetRunUrl: result.datasetRunUrl, summary, config: { model: config.llm.model, judge: useJudge ? config.judge.model : null, policy: config.policy } }, null, 2));
  console.log(`Report saved to ${path.relative(config.paths.root, file)}`);
} finally {
  await shutdownTracing();
}
