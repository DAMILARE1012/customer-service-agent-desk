import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { htmlToMarkdown } from '../transform/htmlToMarkdown.js';
import { syncRemoteFile } from '../remoteFile.js';

const CORPUS_URL = 'https://huggingface.co/datasets/Wix/WixQA/resolve/main/wix_kb_corpus/wix_kb_corpus.jsonl';

const CATEGORY = {
  article: 'How-to',
  feature_request: 'Feature request',
  known_issue: 'Known issue',
};

// Found by counting text repeated across the corpus. Only text with no information is listed here;
// repeated *content* (e.g. a payments FAQ shared by ~130 articles) is kept and de-duplicated later.
const BOILERPLATE = [
  /We are always working to update and improve our products,? and your feedback is (?:greatly|hugely) appreciated\.?/g,
  /^In this article,? (?:learn|you'll learn|we'll show you)[^\n]*$/gim,
  /^Click (?:on )?a question below to learn more[^\n]*$/gim,
];

/** Wix Help Center snapshot (6,221 articles, MIT) from the WixQA benchmark. */
export const wixqaAdapter = {
  id: 'wixqa',
  label: 'WixQA help centre',
  boilerplate: BOILERPLATE,

  async sync({ rawDir, previous }) {
    return syncRemoteFile({ url: CORPUS_URL, dest: path.join(rawDir, 'wix_kb_corpus.jsonl'), previous });
  },

  async *documents({ rawDir, limit }) {
    const lines = readline.createInterface({ input: fs.createReadStream(path.join(rawDir, 'wix_kb_corpus.jsonl')), crlfDelay: Infinity });
    let count = 0;
    for await (const line of lines) {
      if (!line.trim()) continue;
      if (limit && count >= limit) break;
      const record = JSON.parse(line);
      count += 1;
      yield {
        id: record.id,
        title: record.title,
        url: record.url,
        category: CATEGORY[record.article_type] ?? record.article_type,
        audience: 'customer',
        markdown: htmlToMarkdown(record.html_content, { articleUrl: record.url }),
      };
    }
  },
};
