import { abcdAdapter } from './abcd.js';
import { localMarkdownAdapter } from './localMarkdown.js';
import { wixqaAdapter } from './wixqa.js';

/**
 * Every source implements the same two methods:
 *   sync({ rawDir, contentDir, previous }) → { changed, version, contentHash }   cheap change check (+ download)
 *     `previous` is the source's state from the last run; `changed` must mean the content changed.
 *   documents({ rawDir, contentDir, limit })              → async iterable of
 *     { id, title, url, category, audience: 'customer' | 'agent', markdown }
 * plus `boilerplate`: RegExp[] of source-specific noise removed during normalization.
 *
 * Adding a source = one new file here. INGEST_SOURCES picks which run, in priority order
 * (when two sources contain the same text, the earlier source keeps it).
 */
export const ADAPTERS = {
  [localMarkdownAdapter.id]: localMarkdownAdapter,
  [wixqaAdapter.id]: wixqaAdapter,
  [abcdAdapter.id]: abcdAdapter,
};
