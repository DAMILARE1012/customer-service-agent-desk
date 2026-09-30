/** 1-based rank of the first result from a correct article (shared-text duplicates count), or null. */
export function firstRelevantRank(results, goldIds) {
  const gold = new Set(goldIds);
  const index = results.findIndex((r) => gold.has(r.docId) || r.alsoIn.some((a) => gold.has(a.docId)));
  return index < 0 ? null : index + 1;
}

// ─── Graded retrieval metrics (per question) ─────────────────────────────────
// `results` are chunks in rank order; each belongs to docId plus any articles sharing its text (alsoIn).
// Relevance is judged per *article*: several chunks from one correct article count once.

const articlesOf = (result) => [result.docId, ...(result.alsoIn ?? []).map((a) => a.docId ?? a)];

/** Per rank position: does it bring in a correct article not already credited higher up? */
function relevanceAt(results, goldIds, k) {
  const gold = new Set(goldIds);
  const credited = new Set();
  return results.slice(0, k).map((result) => {
    const newGold = articlesOf(result).filter((id) => gold.has(id) && !credited.has(id));
    newGold.forEach((id) => credited.add(id));
    return { relevant: articlesOf(result).some((id) => gold.has(id)), gain: newGold.length > 0 ? 1 : 0, credited: credited.size };
  });
}

/** Share of the correct articles that appear in the top k. */
export function recallAtK(results, goldIds, k) {
  const rel = relevanceAt(results, goldIds, k);
  return (rel.at(-1)?.credited ?? 0) / new Set(goldIds).size;
}

/** Share of the top k results that come from a correct article. */
export function precisionAtK(results, goldIds, k) {
  return relevanceAt(results, goldIds, k).filter((r) => r.relevant).length / k;
}

/** Normalized discounted cumulative gain: rewards correct articles ranked higher. */
export function ndcgAtK(results, goldIds, k) {
  const dcg = relevanceAt(results, goldIds, k).reduce((sum, r, i) => sum + r.gain / Math.log2(i + 2), 0);
  const ideal = Array.from({ length: Math.min(new Set(goldIds).size, k) }, (_, i) => 1 / Math.log2(i + 2)).reduce((a, b) => a + b, 0);
  return ideal ? dcg / ideal : 0;
}

/**
 * Rank-aware context precision (ID-based, as in RAGAS): the average of precision@i over the
 * positions i that hold a relevant chunk. 1 when every relevant chunk sits above every irrelevant one.
 */
export function contextPrecisionAtK(results, goldIds, k) {
  const rel = relevanceAt(results, goldIds, k);
  let hits = 0;
  let sum = 0;
  rel.forEach((r, i) => {
    if (!r.relevant) return;
    hits += 1;
    sum += hits / (i + 1);
  });
  return hits ? sum / hits : 0;
}

export const mean = (values) => {
  const numbers = values.filter((v) => typeof v === 'number' && Number.isFinite(v));
  return numbers.length ? numbers.reduce((a, b) => a + b, 0) / numbers.length : null;
};

export function retrievalMetrics(ranks) {
  const hit = (k) => ranks.filter((r) => r !== null && r <= k).length / ranks.length;
  return {
    hit1: hit(1),
    hit3: hit(3),
    hit5: hit(5),
    hit10: hit(10),
    mrr: ranks.reduce((sum, r) => sum + (r ? 1 / r : 0), 0) / ranks.length,
  };
}

export function quantile(values, q) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * q;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

/**
 * Lowest confidence threshold at which "answering" stays at or above `target` precision, scanning
 * from the most confident question down and stopping at the first dip (conservative).
 * A real question counts as a good answer when its right article is in the top 3 (what the LLM sees);
 * an off-topic question above the threshold always counts as a bad one.
 *
 * @param {{ confidence: number, correct: boolean }[]} positives
 * @param {{ confidence: number }[]} negatives
 */
export function precisionThreshold(positives, negatives, target, { minAnswered = 10 } = {}) {
  const points = [
    ...positives.map((p) => ({ score: p.confidence, good: p.correct })),
    ...negatives.map((n) => ({ score: n.confidence, good: false })),
  ].sort((a, b) => b.score - a.score);

  let answered = 0;
  let good = 0;
  let best = null;
  for (let i = 0; i < points.length; i += 1) {
    answered += 1;
    if (points[i].good) good += 1;
    if (i + 1 < points.length && points[i + 1].score === points[i].score) continue; // evaluate between distinct scores
    if (answered < minAnswered) continue;
    const precision = good / answered;
    if (precision < target) break;
    best = { threshold: points[i].score, precision };
  }
  if (!best) return null;

  return {
    ...best,
    // Share of all real questions the bot would handle alone *and* have the right article for.
    coverage: positives.filter((p) => p.confidence >= best.threshold && p.correct).length / positives.length,
    answeredShare: positives.filter((p) => p.confidence >= best.threshold).length / positives.length,
    offTopicAbove: negatives.filter((n) => n.confidence >= best.threshold).length / negatives.length,
  };
}

/** Below this, a question is almost certainly outside the knowledge base. */
export function noMatchThreshold(positives, negatives, maxMissRate) {
  const threshold = quantile(positives.map((p) => p.confidence), maxMissRate);
  return {
    threshold,
    realBelow: positives.filter((p) => p.confidence < threshold).length / positives.length,
    offTopicBelow: negatives.filter((n) => n.confidence < threshold).length / negatives.length,
  };
}

export const summarize = (values) =>
  values.length
    ? { p5: quantile(values, 0.05), p25: quantile(values, 0.25), median: quantile(values, 0.5), p95: quantile(values, 0.95), max: Math.max(...values), n: values.length }
    : null;
