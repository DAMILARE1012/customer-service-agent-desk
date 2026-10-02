"""Hybrid retriever: vector search and BM25 side by side, merged with reciprocal rank fusion, then
(optionally) the top candidates reordered by a cross-encoder.

`confidence` is the cosine similarity of the top hybrid result, before reranking — what the handoff
policy compares with RAG_NO_MATCH_THRESHOLD (calibrate it with `baton-eval`). Reranking changes the
order, never this "is it in scope?" signal. `relevance` is the reranker's score for the top result.
"""

from dataclasses import dataclass

import numpy as np

from app.config import settings
from app.ingest.normalize import index_form, normalize_query
from app.rag.embedder import Embedder, get_embedder
from app.rag.keyword import KeywordIndex, tokenize
from app.rag.reranker import get_reranker
from app.rag.store import load_index

MODES = ("dense", "keyword", "hybrid", "rerank")


def embed_input(chunk: dict) -> str:
    """The exact text indexed for a chunk (vector + keyword). Title and section path give a short
    chunk the context it needs ("Refunds › Timelines: within 2 business days")."""
    return index_form("\n".join(p for p in (chunk["title"], " > ".join(chunk["headingPath"]), chunk["text"]) if p))


@dataclass
class SearchResult:
    confidence: float
    results: list[dict]
    relevance: float | None = None


class Retriever:
    def __init__(self, embedder: Embedder | None = None):
        index = load_index()
        if not index.manifest:
            raise RuntimeError("No index found. Run `uv run baton-ingest` first.")
        self.embedder = embedder or get_embedder()
        if index.manifest["embedding"]["signature"] != self.embedder.signature:
            raise RuntimeError(
                f"The index was built with {index.manifest['embedding']['signature']} but the embedder is "
                f"{self.embedder.signature}. Run `uv run baton-ingest`."
            )
        self.manifest = index.manifest
        self.chunks = index.chunks
        self.vectors = index.vectors
        self.searchable = np.array([not c.get("duplicateOf") for c in self.chunks], dtype=bool)
        self.audience = np.array([c["audience"] for c in self.chunks])
        self.source = np.array([c["source"] for c in self.chunks])
        self.also_in: dict[str, list[dict]] = {}
        for c in self.chunks:
            if c.get("duplicateOf"):
                self.also_in.setdefault(c["duplicateOf"], []).append(
                    {"source": c["source"], "docId": c["docId"], "title": c["title"], "url": c["url"]}
                )
        self.keyword = KeywordIndex([tokenize(embed_input(c)) if self.searchable[i] else [] for i, c in enumerate(self.chunks)])

    @property
    def size(self) -> int:
        return int(self.searchable.sum())

    def _mask(self, audience: str, sources: list[str] | None) -> np.ndarray:
        mask = self.searchable.copy()
        if audience != "any":
            mask &= self.audience == audience
        if sources:
            mask &= np.isin(self.source, sources)
        return mask

    def _result(self, i: int, similarity: float, keyword_score: float) -> dict:
        c = self.chunks[i]
        return {
            "id": c["id"],
            "source": c["source"],
            "docId": c["docId"],
            "title": c["title"],
            "headingPath": c["headingPath"],
            "url": c["url"],
            "category": c["category"],
            "audience": c["audience"],
            "text": c["text"],
            "alsoIn": self.also_in.get(c["id"], []),
            "similarity": round(float(similarity), 3),
            "keywordScore": round(float(keyword_score), 2),
        }

    def search(self, query: str, *, top_k: int | None = None, audience: str = "customer", sources: list[str] | None = None, mode: str | None = None) -> SearchResult:
        """mode: dense | keyword | hybrid | rerank (hybrid + cross-encoder). Default: rerank when
        RERANKER_MODEL is set, otherwise hybrid."""
        reranker = get_reranker()
        mode = mode or ("rerank" if reranker else "hybrid")
        if mode not in MODES:
            raise ValueError(f"Unknown search mode {mode!r}; use one of {', '.join(MODES)}")
        if mode == "rerank" and reranker is None:
            raise ValueError("Search mode 'rerank' needs RERANKER_MODEL to be set")
        top_k = top_k or settings.retrieval_top_k
        candidates, rrf_k = settings.retrieval_candidates, settings.retrieval_rrf_k
        text = normalize_query(query)
        mask = self._mask(audience, sources)

        similarity = self.vectors @ self.embedder.embed_query(text)  # unit vectors → cosine
        similarity = np.where(mask, similarity, -np.inf)
        dense_ranked = [int(i) for i in np.argsort(-similarity)[: min(candidates, int(mask.sum()))]]
        keyword_hits = self.keyword.search(tokenize(text), limit=candidates, allowed=lambda i: bool(mask[i]))
        keyword_score = dict(keyword_hits)

        if mode == "dense":
            ranked = dense_ranked
        elif mode == "keyword":
            ranked = [i for i, _ in keyword_hits]
        else:
            fused: dict[int, float] = {}
            for rank, i in enumerate(dense_ranked):
                fused[i] = fused.get(i, 0) + 1 / (rrf_k + rank + 1)
            for rank, (i, _) in enumerate(keyword_hits):
                fused[i] = fused.get(i, 0) + 1 / (rrf_k + rank + 1)
            ranked = [i for i, _ in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]

        confidence = round(float(similarity[ranked[0]]), 3) if ranked else 0.0
        if mode != "rerank":
            results = [self._result(i, similarity[i], keyword_score.get(i, 0)) for i in ranked[:top_k]]
            return SearchResult(confidence=confidence, results=results)

        pool = ranked[: max(settings.rerank_candidates, top_k)]
        scores = reranker.score(text, [embed_input(self.chunks[i]) for i in pool])
        order = np.argsort(-scores, kind="stable")[:top_k]
        results = [{**self._result(pool[j], similarity[pool[j]], keyword_score.get(pool[j], 0)), "rerankScore": round(float(scores[j]), 3)} for j in order]
        return SearchResult(confidence=confidence, results=results, relevance=results[0]["rerankScore"] if results else None)
