import assert from 'node:assert/strict';
import { test } from 'node:test';
import { htmlToMarkdown } from './htmlToMarkdown.js';

const URL = 'https://support.example.com/en/article/demo';

test('keeps headings and lists, drops images and link markup', () => {
  const html = `
    <div data-component-type="heading"><h2>Connecting a domain</h2></div>
    <div data-component-type="text"><ol><li>Click <strong>Settings</strong>.</li><li>Click the icon <img src="x.png">at the top.</li></ol></div>
    <div data-component-type="image"><img src="shot.png" alt="A screenshot"></div>`;
  assert.equal(htmlToMarkdown(html, { articleUrl: URL }), '## Connecting a domain\n\n1. Click Settings.\n2. Click the icon at the top.');
});

test('drops in-page tables of contents', () => {
  const html = `<ul><li><a href="${URL}#step-1">Step 1</a></li><li><a href="#step-2">Step 2</a></li></ul><div>Body text.</div>`;
  assert.equal(htmlToMarkdown(html, { articleUrl: URL }), 'Body text.');
});

test('keeps ordinary link lists', () => {
  const html = '<ul><li><a href="https://other.example.com/a">Other article</a></li></ul>';
  assert.equal(htmlToMarkdown(html, { articleUrl: URL }), '- Other article');
});

test('labels tabs and callouts so the label stays with its content', () => {
  const html = `
    <div data-component-type="tabs"><div class="tabs-wrapper">
      <div class="headings-wrapper"><div class="tab-heading">Wix Editor</div><div class="tab-heading">Studio Editor</div></div>
      <div class="tab-contents-wrapper"><div class="tab-content"><div>Click Add.</div></div><div class="tab-content"><div>Click Plus.</div></div></div>
    </div></div>
    <div data-component-type="informative"><div class="info-title">Note:</div><div class="info-content"><div>Save first.</div></div></div>`;
  assert.equal(htmlToMarkdown(html), 'Wix Editor:\nClick Add.\n\nStudio Editor:\nClick Plus.\n\nNote:\nSave first.');
});

test('question-like collapsibles become sub-headings; UI toggles disappear', () => {
  const html = `
    <div data-component-type="collapsible"><h4 class="collapsible-title">Is my currency supported?</h4><div class="collapsible-content"><div>Most are.</div></div></div>
    <div data-component-type="collapsible"><h4 class="collapsible-title">Show me how</h4><div class="collapsible-content"><div>Do this.</div></div></div>`;
  assert.equal(htmlToMarkdown(html), '#### Is my currency supported?\n\nMost are.\n\nDo this.');
});

test('renders two-column tables as key: value lines', () => {
  const html = `<div data-component-type="table"><table>
    <thead><tr><th>General Info</th><th></th></tr></thead>
    <tbody><tr><td>Supported countries</td><td>United States</td></tr><tr><td>Fees</td><td>2.6% + 0.20 USD</td></tr></tbody>
  </table></div>`;
  assert.equal(htmlToMarkdown(html), 'General Info\nSupported countries: United States\nFees: 2.6% + 0.20 USD');
});
