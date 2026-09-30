import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  contextPrecisionAtK,
  firstRelevantRank,
  ndcgAtK,
  noMatchThreshold,
  precisionAtK,
  precisionThreshold,
  recallAtK,
  retrievalMetrics,
} from './metrics.js';

const r = (docId, alsoIn = []) => ({ docId, alsoIn: alsoIn.map((id) => ({ docId: id })) });

test('recall@k counts each correct article once, including shared chunks', () => {
  const results = [r('x'), r('a'), r('a'), r('y', ['b'])];
  assert.equal(recallAtK(results, ['a', 'b'], 2), 0.5);
  assert.equal(recallAtK(results, ['a', 'b'], 4), 1);
});

test('precision@k is the share of top-k chunks from correct articles', () => {
  assert.equal(precisionAtK([r('a'), r('x'), r('a'), r('y')], ['a'], 4), 0.5);
});

test('nDCG@k is 1 for a perfect ranking and lower when the hit is further down', () => {
  assert.equal(ndcgAtK([r('a'), r('x')], ['a'], 2), 1);
  assert.ok(Math.abs(ndcgAtK([r('x'), r('a')], ['a'], 2) - 1 / Math.log2(3)) < 1e-9);
  assert.equal(ndcgAtK([r('a'), r('a')], ['a'], 2), 1, 'a second chunk of the same article adds no gain');
});

test('context precision rewards relevant chunks ranked above irrelevant ones', () => {
  assert.equal(contextPrecisionAtK([r('a'), r('a'), r('x')], ['a'], 3), 1);
  assert.equal(contextPrecisionAtK([r('x'), r('a')], ['a'], 2), 0.5);
  assert.equal(contextPrecisionAtK([r('x')], ['a'], 1), 0);
});

test('firstRelevantRank counts articles that share a de-duplicated chunk', () => {
  const results = [
    { docId: 'a', alsoIn: [] },
    { docId: 'b', alsoIn: [{ docId: 'gold' }] },
  ];
  assert.equal(firstRelevantRank(results, ['gold']), 2);
  assert.equal(firstRelevantRank(results, ['missing']), null);
});

test('retrievalMetrics computes hit@k and MRR', () => {
  const m = retrievalMetrics([1, 3, null, 2]);
  assert.equal(m.hit1, 0.25);
  assert.equal(m.hit3, 0.75);
  assert.equal(m.mrr, (1 + 1 / 3 + 0 + 1 / 2) / 4);
});

test('precisionThreshold picks the lowest score that keeps precision on target', () => {
  // 10 confident correct answers, then a band of mostly wrong ones.
  const positives = [
    ...Array.from({ length: 10 }, (_, i) => ({ confidence: 0.9 - i * 0.01, correct: true })),
    ...Array.from({ length: 10 }, (_, i) => ({ confidence: 0.7 - i * 0.01, correct: i % 4 === 0 })),
  ];
  const negatives = [{ confidence: 0.5 }];
  const result = precisionThreshold(positives, negatives, 0.8);
  // 0.70 → 11/11, 0.69 → 11/12, 0.68 → 11/13 = 85% (still ≥ 80%), 0.67 → 11/14 = 79% (stop).
  assert.ok(Math.abs(result.threshold - 0.68) < 1e-9, `threshold was ${result.threshold}`);
  assert.ok(result.precision >= 0.8);
  assert.equal(result.offTopicAbove, 0);
});

test('precisionThreshold returns null when the target is unreachable', () => {
  const positives = Array.from({ length: 20 }, (_, i) => ({ confidence: 0.8 - i * 0.01, correct: false }));
  assert.equal(precisionThreshold(positives, [], 0.5), null);
});

test('noMatchThreshold keeps the miss rate at or under the limit', () => {
  const positives = Array.from({ length: 100 }, (_, i) => ({ confidence: 0.5 + i * 0.004 }));
  const negatives = [{ confidence: 0.3 }, { confidence: 0.6 }];
  const result = noMatchThreshold(positives, negatives, 0.05);
  assert.ok(result.realBelow <= 0.05);
  assert.equal(result.offTopicBelow, 0.5);
});
