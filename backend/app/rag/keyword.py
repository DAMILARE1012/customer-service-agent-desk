"""BM25 keyword index. Complements vector search on exact strings embeddings are weak at: order
numbers, promo codes (SAVE20), prices (249.99), product and feature names."""

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable

STOPWORDS = set(
    """a an the and or but if then so to of in on at for from by with about as is are was were be been being am
    i im me my we our us you your it its this that these those do does did have has had can could would
    should will just not no yes please there here what which who whom into up out over any some also very
    get got how when where why""".split()
)

_TOKEN = re.compile(r"[a-z0-9]+(?:\.\d+)?")


def _stem(word: str) -> str:
    """Light suffix stripping so "refunds"/"refunded" match "refund". Numbers and codes are left intact."""
    if any(c.isdigit() for c in word) or len(word) <= 4:
        return word
    if word.endswith("ing") and len(word) > 6:
        return word[:-3]
    if word.endswith("ed") and len(word) > 5:
        return word[:-2]
    if word.endswith("es") and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower().replace("'", "")) if len(t) > 1 and t not in STOPWORDS]


class KeywordIndex:
    def __init__(self, documents: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.size = len(documents)
        self.lengths = [len(tokens) for tokens in documents]
        self.average_length = sum(self.lengths) / max(1, self.size)
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for doc, tokens in enumerate(documents):
            for term, tf in Counter(tokens).items():
                self.postings[term].append((doc, tf))

    def search(self, tokens: list[str], limit: int = 50, allowed: Callable[[int], bool] | None = None) -> list[tuple[int, float]]:
        """[(doc_index, score)] best first."""
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokens):
            posting = self.postings.get(term)
            if not posting:
                continue
            idf = math.log(1 + (self.size - len(posting) + 0.5) / (len(posting) + 0.5))
            for doc, tf in posting:
                if allowed and not allowed(doc):
                    continue
                norm = 1 - self.b + self.b * self.lengths[doc] / self.average_length
                scores[doc] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
