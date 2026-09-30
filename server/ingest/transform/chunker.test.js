import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chunkMarkdown } from './chunker.js';

// One token per word keeps the arithmetic in these tests easy to follow.
const countTokens = (text) => text.split(/\s+/).filter(Boolean).length;
const words = (n, word = 'lorem') => Array.from({ length: n }, () => word).join(' ');
const options = { countTokens, minTokens: 10, targetTokens: 60, maxTokens: 100 };

test('splits at headings and records the heading path', () => {
  const md = `${words(20)}\n\n## Billing\n\n${words(20, 'bill')}\n\n### Refunds\n\n${words(20, 'refund')}`;
  const chunks = chunkMarkdown(md, options);
  assert.deepEqual(chunks.map((c) => c.headingPath), [[], ['Billing'], ['Billing', 'Refunds']]);
});

test('folds a tiny section into the next one, keeping its heading inline', () => {
  const md = `## Tiny\n\n${words(3, 'tiny')}\n\n## Big\n\n${words(30, 'big')}`;
  const [chunk, ...rest] = chunkMarkdown(md, options);
  assert.equal(rest.length, 0);
  assert.deepEqual(chunk.headingPath, ['Tiny']);
  assert.match(chunk.text, /tiny tiny tiny\n\n## Big\nbig/);
});

test('an intro line stays with the list it introduces', () => {
  const md = `Do the following:\n\n${Array.from({ length: 6 }, (_, i) => `${i + 1}. ${words(12, 'step')}`).join('\n')}`;
  const [first] = chunkMarkdown(md, options);
  assert.match(first.text, /^Do the following:\n\n1\. step/);
});

test('no chunk ends with a dangling heading', () => {
  const md = `## A\n\n${words(5)}\n\n## B\n\n${words(95, 'b')}\n\n## C\n\n${words(40, 'c')}`;
  for (const chunk of chunkMarkdown(md, options)) assert.doesNotMatch(chunk.text, /(^|\n)#{1,6} [^\n]+$/);
});

test('oversized blocks are split to fit maxTokens', () => {
  const sentences = Array.from({ length: 30 }, () => `${words(9, 'word')}.`).join(' ');
  const chunks = chunkMarkdown(sentences, options);
  assert.ok(chunks.length > 1);
  for (const chunk of chunks) assert.ok(chunk.tokens <= options.maxTokens, `chunk has ${chunk.tokens} tokens`);
});

test('editing one section only changes that section’s chunks', () => {
  const doc = (billingWord) =>
    `## Shipping\n\n${words(30, 'ship')}\n\n## Billing\n\n${words(30, billingWord)}\n\n## Returns\n\n${words(30, 'return')}`;
  const before = chunkMarkdown(doc('bill'), options).map((c) => c.text);
  const after = chunkMarkdown(doc('invoice'), options).map((c) => c.text);
  const changed = before.filter((text, i) => text !== after[i]);
  assert.equal(before.length, after.length);
  assert.equal(changed.length, 1, 'only the Billing chunk differs, so only it is re-embedded');
});
