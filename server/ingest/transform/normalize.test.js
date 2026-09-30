import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cleanText, indexForm, normalizeQuery } from './normalize.js';

const ch = (codePoint) => String.fromCodePoint(codePoint);

test('removes invisible characters and normalises odd spaces', () => {
  const input = `Hello${ch(0xa0)}world${ch(0x200b)}${ch(0xfeff)}`;
  assert.equal(cleanText(input), 'Hello world');
});

test('keeps identifiers, prices, emails and arrows intact', () => {
  const input = 'Order #48213 cost $249.99 — code SAVE20, email a.b@example.com, Account → Orders';
  assert.equal(cleanText(input), input);
});

test('collapses runs of spaces and blank lines but keeps list indentation', () => {
  const input = 'Steps:\n\n\n\n1. Open   settings\n  - nested   item';
  assert.equal(cleanText(input), 'Steps:\n\n1. Open settings\n  - nested item');
});

test('NFKC folds compatibility characters such as ligatures', () => {
  assert.equal(cleanText(`${ch(0xfb01)}le`), 'file');
});

test('applies per-source boilerplate patterns', () => {
  const input = 'Real content.\nWe are always working to update and improve our products, and your feedback is greatly appreciated.';
  const boilerplate = [/We are always working[^\n]*appreciated\./g];
  assert.equal(cleanText(input, { boilerplate }), 'Real content.');
});

test('indexForm folds quotes and dashes for search only', () => {
  const display = cleanText(`it${ch(0x2019)}s ${ch(0x201c)}fine${ch(0x201d)} ${ch(0x2013)} 3${ch(0x2013)}5 days`);
  assert.equal(display.includes(ch(0x2019)), true, 'display text keeps typography');
  assert.equal(indexForm(display), `it's "fine" - 3-5 days`);
  assert.equal(normalizeQuery(`  it${ch(0x2019)}s  `), "it's");
});
