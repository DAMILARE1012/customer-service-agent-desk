import { NodeType, parse } from 'node-html-parser';

// Converts help-centre HTML into light markdown that keeps the structure chunking depends on:
// `#` headings, `-`/`1.` lists and blank-line separated blocks. Formatting that only adds noise
// to embeddings (bold, links, images) is reduced to plain text.
//
// Written against the Wix help-centre markup (data-component-type="…" blocks) but falls back to
// generic handling for ordinary HTML.

const BLOCK_TAGS = new Set(['div', 'p', 'section', 'article', 'blockquote', 'ul', 'ol', 'li', 'table', 'pre', 'figure', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']);
const DROPPED_TAGS = new Set(['img', 'svg', 'script', 'style', 'iframe', 'video', 'figure', 'hr', 'noscript']);
const HEADING_LEVEL = { h1: 2, h2: 2, h3: 3, h4: 4, h5: 4, h6: 4 };
const DROPPED_COMPONENTS = new Set(['image', 'video', 'iframe', 'line']);
// Collapsible titles that are UI affordances, not topics.
const GENERIC_TOGGLE = /^(show me how|tell me more|learn more|show me more|click here|read more)\.?$/i;

const tagOf = (node) => node.rawTagName?.toLowerCase() ?? '';
const isElement = (node) => node.nodeType === NodeType.ELEMENT_NODE;
const collapse = (text) => text.replace(/[ \t]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{2,}/g, '\n').trim();
const heading = (level, text) => (text ? [`${'#'.repeat(level)} ${text}`] : []);

function rawInline(node) {
  if (!isElement(node)) return node.text; // decodes entities
  const tag = tagOf(node);
  if (tag === 'br') return '\n';
  if (DROPPED_TAGS.has(tag)) return ' '; // inline icons sit between words: "the Connect <img>at the top"
  const inner = node.childNodes.map(rawInline).join('');
  return BLOCK_TAGS.has(tag) ? ` ${inner} ` : inner;
}

const inline = (node) => collapse(rawInline(node));

/** Prefix a label ("Note:", "Wix Editor:") onto the first block so the two are never split apart. */
function labelled(label, blocks) {
  if (!label) return blocks;
  if (!blocks.length) return [label];
  return [`${label}\n${blocks[0]}`, ...blocks.slice(1)];
}

function isTableOfContents(list, articleUrl) {
  const items = list.childNodes.filter((c) => isElement(c) && tagOf(c) === 'li');
  if (!items.length) return false;
  return items.every((li) => {
    const href = li.querySelector('a')?.getAttribute('href') ?? '';
    return href.startsWith('#') || (articleUrl && href.startsWith(`${articleUrl}#`));
  });
}

function renderList(list, ctx, depth = 0) {
  const ordered = tagOf(list) === 'ol';
  const lines = [];
  let n = 0;
  for (const li of list.childNodes.filter((c) => isElement(c) && tagOf(c) === 'li')) {
    const nested = li.childNodes.filter((c) => isElement(c) && ['ul', 'ol'].includes(tagOf(c)));
    const own = li.childNodes.filter((c) => !nested.includes(c));
    const text = collapse(own.map(rawInline).join('')).replace(/\n/g, ' ');
    if (text) lines.push(`${'  '.repeat(depth)}${ordered ? `${++n}.` : '-'} ${text}`);
    for (const sub of nested) lines.push(...renderList(sub, ctx, depth + 1));
  }
  return lines;
}

function renderTable(table) {
  if (!table) return [];
  const headers = table.querySelectorAll('thead th').map(inline);
  const meaningfulHeaders = headers.filter(Boolean);
  const lines = [];
  // A header row with a single label ("General Info") is a caption, not column names.
  if (meaningfulHeaders.length === 1) lines.push(meaningfulHeaders[0]);

  for (const row of table.querySelectorAll('tbody tr')) {
    const cells = row.querySelectorAll('td').map(inline);
    if (!cells.some(Boolean)) continue;
    if (cells.length === 2) lines.push(`${cells[0]}: ${cells[1]}`);
    else if (meaningfulHeaders.length === cells.length) lines.push(cells.map((c, i) => `${headers[i]}: ${c}`).join('; '));
    else lines.push(cells.join(' | '));
  }
  return lines.length ? [lines.join('\n')] : [];
}

function renderComponent(type, node, ctx) {
  if (DROPPED_COMPONENTS.has(type)) return [];

  switch (type) {
    case 'heading':
    case 'subheading': {
      const h = node.querySelector('h1, h2, h3, h4, h5, h6');
      return heading(h ? HEADING_LEVEL[tagOf(h)] : 3, inline(h ?? node));
    }
    case 'informative': {
      const title = inline(node.querySelector('.info-title') ?? { nodeType: NodeType.TEXT_NODE, text: '' });
      const content = node.querySelector('.info-content');
      return labelled(title, content ? renderChildren(content, ctx) : []);
    }
    case 'collapsible': {
      const title = inline(node.querySelector('.collapsible-title') ?? { nodeType: NodeType.TEXT_NODE, text: '' });
      const content = node.querySelector('.collapsible-content');
      const blocks = content ? renderChildren(content, ctx) : [];
      if (!title || GENERIC_TOGGLE.test(title)) return blocks;
      // Real topics ("Is my currency supported?") become sub-sections; short labels stay inline.
      const isTopic = title.endsWith('?') || title.split(/\s+/).length >= 4;
      return isTopic ? [...heading(4, title), ...blocks] : labelled(`${title}:`, blocks);
    }
    case 'tabs': {
      const labels = node.querySelectorAll('.tab-heading').map(inline);
      const panes = node.querySelector('.tab-contents-wrapper')?.childNodes.filter(isElement) ?? [];
      return panes.flatMap((pane, i) => labelled(labels[i] ? `${labels[i]}:` : '', renderChildren(pane, ctx)));
    }
    case 'table':
      return renderTable(node.querySelector('table'));
    case 'code':
    case 'html':
    case 'markdown': {
      const text = node.text.trim();
      return text ? [text] : [];
    }
    default:
      return renderChildren(node, ctx);
  }
}

/** Renders children, gluing runs of inline content ("Click <b>Save</b> now") into one block. */
function renderChildren(node, ctx) {
  const blocks = [];
  let run = [];
  const flush = () => {
    const text = collapse(run.map(rawInline).join(''));
    if (text) blocks.push(text);
    run = [];
  };

  for (const child of node.childNodes) {
    const isBlock = isElement(child) && (BLOCK_TAGS.has(tagOf(child)) || child.getAttribute('data-component-type'));
    if (!isBlock) {
      run.push(child);
      continue;
    }
    flush();
    blocks.push(...renderBlock(child, ctx));
  }
  flush();
  return blocks;
}

function renderBlock(node, ctx) {
  const component = node.getAttribute('data-component-type');
  if (component) return renderComponent(component, node, ctx);

  const tag = tagOf(node);
  if (DROPPED_TAGS.has(tag)) return [];
  if (tag in HEADING_LEVEL) return heading(HEADING_LEVEL[tag], inline(node));
  if (tag === 'ul' || tag === 'ol') {
    if (isTableOfContents(node, ctx.articleUrl)) return [];
    const lines = renderList(node, ctx);
    return lines.length ? [lines.join('\n')] : [];
  }
  if (tag === 'table') return renderTable(node);
  if (tag === 'pre') return [node.text.trim()].filter(Boolean);
  return renderChildren(node, ctx);
}

/**
 * @param {string} html
 * @param {{ articleUrl?: string }} [options] used to recognise in-page tables of contents
 * @returns {string} markdown
 */
export function htmlToMarkdown(html, { articleUrl } = {}) {
  const root = parse(html, { blockTextElements: { script: false, style: false, noscript: false, pre: true } });
  return renderChildren(root, { articleUrl }).join('\n\n');
}
