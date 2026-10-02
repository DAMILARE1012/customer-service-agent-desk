"""Retriever ranking logic on a tiny in-memory index — no model downloads (fake embedder and reranker)."""

import numpy as np
import pytest

from app.rag import retriever as retriever_module
from app.rag.keyword import KeywordIndex, tokenize
from app.rag.retriever import Retriever, embed_input


def chunk(i: int, title: str, text: str) -> dict:
    return {"id": f"c{i}", "source": "wixqa", "docId": f"d{i}", "title": title, "headingPath": [], "url": f"https://x/{i}",
            "category": "help", "audience": "customer", "text": text}  # fmt: skip


CHUNKS = [
    chunk(0, "Connect a domain", "Point your domain's DNS records to your site."),
    chunk(1, "Buy a domain", "Purchase a new domain from the domains page."),
    chunk(2, "Refund policy", "Refunds are issued within 14 days."),
]


class FakeEmbedder:
    signature = "fake"

    def embed_query(self, _text: str) -> np.ndarray:
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


class FakeReranker:
    """Prefers chunk 1, then 0, then 2 — the opposite of the vector ranking for the first two."""

    model = "fake-reranker"

    def score(self, _query: str, passages: list[str]) -> np.ndarray:
        order = {embed_input(c): s for c, s in zip(CHUNKS, (0.4, 0.9, 0.1), strict=True)}
        return np.array([order[p] for p in passages], dtype=np.float32)


@pytest.fixture
def retriever() -> Retriever:
    r = Retriever.__new__(Retriever)  # skip loading the on-disk index
    r.embedder, r.manifest, r.chunks = FakeEmbedder(), {"builtAt": "test"}, CHUNKS
    r.vectors = np.array([[0.9, 0.436, 0], [0.8, 0.6, 0], [0.1, 0.995, 0]], dtype=np.float32)
    r.searchable = np.ones(len(CHUNKS), dtype=bool)
    r.audience = np.array([c["audience"] for c in CHUNKS])
    r.source = np.array([c["source"] for c in CHUNKS])
    r.also_in = {}
    r.keyword = KeywordIndex([tokenize(embed_input(c)) for c in CHUNKS])
    return r


def test_default_mode_is_hybrid_without_a_reranker(retriever, monkeypatch):
    monkeypatch.setattr(retriever_module, "get_reranker", lambda: None)
    found = retriever.search("connect my domain", top_k=3)
    assert found.results[0]["id"] == "c0"
    assert found.relevance is None and "rerankScore" not in found.results[0]
    with pytest.raises(ValueError):
        retriever.search("connect my domain", mode="rerank")


def test_rerank_reorders_but_keeps_the_scope_confidence(retriever, monkeypatch):
    monkeypatch.setattr(retriever_module, "get_reranker", lambda: FakeReranker())
    hybrid = retriever.search("connect my domain", top_k=3, mode="hybrid")
    reranked = retriever.search("connect my domain", top_k=3)  # default is rerank when one is configured

    assert [r["id"] for r in reranked.results] == ["c1", "c0", "c2"]
    assert [r["rerankScore"] for r in reranked.results] == [0.9, 0.4, 0.1]
    assert reranked.relevance == 0.9
    # The no-match gate was calibrated on the hybrid top result's cosine; reranking must not move it.
    assert reranked.confidence == hybrid.confidence == 0.9


def test_unknown_mode_is_rejected(retriever, monkeypatch):
    monkeypatch.setattr(retriever_module, "get_reranker", lambda: None)
    with pytest.raises(ValueError):
        retriever.search("x", mode="semantic")
