import { round2 } from './text.js';

// Prefix → weight. A production system would call a classifier; this keeps the demo deterministic.
const NEGATIVE = {
  frustrat: 2, ridiculous: 2, terrible: 2, awful: 2, worst: 2, useless: 2, unacceptable: 2.5,
  angry: 2, furious: 3, hate: 2, scam: 3, annoy: 1.5, disappoint: 1.5, upset: 1.5, waste: 1.5,
  joke: 1, seriously: 1, again: 0.5, never: 0.5, wrong: 0.75, bad: 1, 'not help': 1.5,
};
const POSITIVE = {
  thank: 1.5, thx: 1, great: 1.5, perfect: 2, awesome: 2, helpful: 1.5, love: 1.5, appreciate: 1.5, good: 1, nice: 1,
};

function sumMatches(text, lexicon) {
  return Object.entries(lexicon).reduce((sum, [prefix, weight]) => {
    const pattern = new RegExp(`\\b${prefix}`, 'g');
    return sum + (text.match(pattern)?.length ?? 0) * weight;
  }, 0);
}

export function scoreSentiment(rawText) {
  const text = rawText.toLowerCase();
  let negative = sumMatches(text, NEGATIVE);
  const positive = sumMatches(text, POSITIVE);

  if (/!{2,}/.test(rawText)) negative += 0.75;
  if ((rawText.match(/\b[A-Z]{4,}\b/g) ?? []).length > 0) negative += 0.75;

  if (negative === 0 && positive === 0) return 0;
  return round2((positive - negative) / (positive + negative + 1));
}

export function sentimentLabel(score) {
  if (score <= -0.5) return 'Frustrated';
  if (score < -0.15) return 'Negative';
  if (score > 0.25) return 'Positive';
  return 'Neutral';
}
