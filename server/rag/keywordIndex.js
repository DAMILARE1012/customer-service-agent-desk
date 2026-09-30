// BM25 keyword index. Complements vector search on exact strings embeddings are weak at:
// order numbers, promo codes (SAVE20), prices (249.99), product and feature names.

const STOPWORDS = new Set(
  `a an the and or but if then so to of in on at for from by with about as is are was were be been being am
   i im me my we our us you your it its this that these those do does did have has had can could would
   should will just not no yes please there here what which who whom into up out over any some also very
   get got how when where why`.split(/\s+/),
);

// Light suffix stripping so "refunds"/"refunded" match "refund". Numbers and codes are left intact.
function stem(word) {
  if (/\d/.test(word) || word.length <= 4) return word;
  if (word.endsWith('ing') && word.length > 6) return word.slice(0, -3);
  if (word.endsWith('ed') && word.length > 5) return word.slice(0, -2);
  if (word.endsWith('es') && word.length > 5) return word.slice(0, -2);
  if (word.endsWith('s') && !word.endsWith('ss')) return word.slice(0, -1);
  return word;
}

export function tokenize(text) {
  return (text.toLowerCase().replace(/'/g, '').match(/[a-z0-9]+(?:\.\d+)?/g) ?? [])
    .filter((token) => token.length > 1 && !STOPWORDS.has(token))
    .map(stem);
}

export class KeywordIndex {
  /** @param {string[][]} documents token lists; index i ↔ chunk i */
  constructor(documents, { k1 = 1.2, b = 0.75 } = {}) {
    this.k1 = k1;
    this.b = b;
    this.size = documents.length;
    this.lengths = new Uint32Array(documents.length);
    this.postings = new Map(); // term → [docIndex, termFrequency][]

    let total = 0;
    documents.forEach((tokens, doc) => {
      this.lengths[doc] = tokens.length;
      total += tokens.length;
      const counts = new Map();
      for (const token of tokens) counts.set(token, (counts.get(token) ?? 0) + 1);
      for (const [term, tf] of counts) {
        if (!this.postings.has(term)) this.postings.set(term, []);
        this.postings.get(term).push([doc, tf]);
      }
    });
    this.averageLength = total / Math.max(1, documents.length);
  }

  /** @returns {{ index: number, score: number }[]} best first */
  search(tokens, { limit = 50, filter = null } = {}) {
    const scores = new Map();
    for (const term of new Set(tokens)) {
      const posting = this.postings.get(term);
      if (!posting) continue;
      const idf = Math.log(1 + (this.size - posting.length + 0.5) / (posting.length + 0.5));
      for (const [doc, tf] of posting) {
        if (filter && !filter(doc)) continue;
        const lengthNorm = 1 - this.b + (this.b * this.lengths[doc]) / this.averageLength;
        scores.set(doc, (scores.get(doc) ?? 0) + (idf * tf * (this.k1 + 1)) / (tf + this.k1 * lengthNorm));
      }
    }
    return [...scores]
      .sort((a, b) => b[1] - a[1])
      .slice(0, limit)
      .map(([index, score]) => ({ index, score }));
  }
}
