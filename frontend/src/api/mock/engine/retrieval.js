import { KNOWLEDGE_BASE } from '../data/knowledgeBase.js';
import { round2, tokenize, truncate } from './text.js';

// Stand-in for a vector store. Keyword hits weigh more than incidental body hits;
// the score blends match strength with how much of the question was covered.
const INDEX = KNOWLEDGE_BASE.map((article) => ({
  article,
  keywords: new Set(article.keywords.flatMap(tokenize)),
  body: new Set(tokenize(`${article.title} ${article.content}`)),
}));

const KEYWORD_WEIGHT = 1;
const BODY_WEIGHT = 0.35;

function scoreArticle(terms, { keywords, body }) {
  let weight = 0;
  const matched = [];
  for (const term of terms) {
    if (keywords.has(term)) weight += KEYWORD_WEIGHT;
    else if (body.has(term)) weight += BODY_WEIGHT;
    else continue;
    matched.push(term);
  }
  const strength = weight / (weight + 1);
  const coverage = matched.length / terms.length;
  return { score: round2(0.65 * strength + 0.35 * coverage), matched };
}

export function retrieve(query, { topK = 3 } = {}) {
  const terms = [...new Set(tokenize(query))];
  if (terms.length === 0) return { terms, hits: [], confidence: 0 };

  const hits = INDEX.map((entry) => {
    const { score, matched } = scoreArticle(terms, entry);
    const { id, title, category, url, content, answer } = entry.article;
    return { id, title, category, url, answer, snippet: truncate(content, 180), score, matchedTerms: matched };
  })
    .filter((hit) => hit.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);

  return { terms, hits, confidence: hits[0]?.score ?? 0 };
}

export const toSourceRef = ({ id, title, url, category, snippet, score }) => ({ id, title, url, category, snippet, score });
