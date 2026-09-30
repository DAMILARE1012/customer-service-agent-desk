import { propagateAttributes, startActiveObservation } from '@langfuse/tracing';
import { config } from '../config.js';
import { judge } from '../eval/judge.js';
import { onlineEvalScore } from './metrics.js';
import { getLangfuse } from './tracing.js';

// Online evaluation: a sample of live answers is scored by the LLM judge in the background
// (faithfulness, relevance — no reference answer exists for live traffic). Scores attach to the
// answer's trace in Langfuse and feed the online_eval_score histogram in Prometheus.

const MAX_QUEUE = 100; // under load, drop samples rather than pile up judge calls
const queue = [];
let draining = false;

/** Queue an answer for judging, subject to ONLINE_EVAL_SAMPLE_RATE. Never blocks the reply. */
export function maybeScoreAnswer({ traceId, question, contexts, answer }) {
  const rate = config.observability.onlineEvalSampleRate;
  if (!traceId || !answer || rate <= 0 || Math.random() >= rate || queue.length >= MAX_QUEUE) return;
  queue.push({ traceId, question, contexts, answer });
  void drain();
}

async function drain() {
  if (draining) return;
  draining = true;
  while (queue.length) {
    const job = queue.shift();
    try {
      const verdict = await propagateAttributes({ traceName: 'online-eval', tags: ['evaluation', 'online'] }, () =>
        startActiveObservation(
          'online-eval',
          async (span) => {
            span.update({ input: { question: job.question, answer: job.answer }, metadata: { scoredTraceId: job.traceId } });
            const result = await judge({ question: job.question, contexts: job.contexts, answer: job.answer });
            span.update({ output: result });
            return result;
          },
          { asType: 'evaluator' },
        ),
      );
      record(job.traceId, verdict);
    } catch (error) {
      console.warn(`[online-eval] skipped: ${error.message}`);
    }
  }
  draining = false;
}

function record(traceId, verdict) {
  if (!verdict) return;
  const langfuse = getLangfuse();
  const scores = [
    { name: 'faithfulness', value: verdict.faithfulness, comment: verdict.unsupportedClaims.length ? `Unsupported: ${verdict.unsupportedClaims.join(' | ')}` : verdict.reasoning },
    { name: 'answer_relevance', value: verdict.answerRelevance, comment: verdict.reasoning },
  ];
  for (const { name, value, comment } of scores) {
    if (value == null) continue;
    onlineEvalScore.observe({ metric: name }, value);
    langfuse?.score.create({ traceId, name, value, comment, dataType: 'NUMERIC' });
  }
}
