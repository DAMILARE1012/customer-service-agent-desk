import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from '../config.js';
import { syncRemoteFile } from '../ingest/remoteFile.js';

const BASE = 'https://huggingface.co/datasets/Wix/WixQA/resolve/main';

// WixQA question sets. Each question lists the help-centre articles needed to answer it.
export const QUESTION_SETS = {
  expert: { file: 'wixqa_expertwritten/test.jsonl', description: '200 real support tickets, answers written by Wix experts' },
  simulated: { file: 'wixqa_simulated/test.jsonl', description: '200 questions distilled from real support chats' },
};

/** @returns {Promise<{ question: string, answer: string, articleIds: string[] }[]>} */
export async function loadQuestions(setName) {
  const set = QUESTION_SETS[setName];
  if (!set) throw new Error(`Unknown question set "${setName}". Use: ${Object.keys(QUESTION_SETS).join(', ')}`);
  const dest = path.join(config.paths.raw, 'wixqa', 'eval', path.basename(path.dirname(set.file)) + '.jsonl');
  // A fixed benchmark: download once, then reuse (delete the file to fetch it again).
  if (!existsSync(dest)) await syncRemoteFile({ url: `${BASE}/${set.file}`, dest });
  const lines = (await fs.readFile(dest, 'utf8')).split('\n').filter(Boolean);
  return lines.map((line) => {
    const { question, answer, article_ids: articleIds } = JSON.parse(line);
    return { question, answer, articleIds };
  });
}
