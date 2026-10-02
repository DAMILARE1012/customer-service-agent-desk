"""Local embeddings with sentence-transformers (no API key, no rate limits). One process-wide instance.

Chosen over fastembed after measuring both on this corpus: same vectors (cosine agreement 1.0000),
6.4 vs 3.8 chunks/s on CPU. Token counting uses the model's own tokenizer with truncation disabled —
the chunker needs true lengths to keep chunks under the model's 512-token window.
"""

import os
import threading
from functools import cached_property

import numpy as np
from tokenizers import Tokenizer

from app.config import settings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows without developer mode copies instead


class Embedder:
    def __init__(self, model: str = settings.embedding_model):
        self.model = model
        self.query_prefix = settings.embedding_query_prefix
        self._lock = threading.Lock()

    @cached_property
    def _engine(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model, cache_folder=str(settings.models_path), device="cpu")

    @cached_property
    def _tokenizer(self) -> Tokenizer:
        tokenizer = Tokenizer.from_pretrained(self.model)
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer

    @cached_property
    def dim(self) -> int:
        return int(self._engine.get_embedding_dimension())

    @property
    def signature(self) -> str:
        """Everything that changes a document vector; part of each chunk's cache key."""
        return f"{self.model}|sentence-transformers|normalized"

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text).ids)  # includes [CLS]/[SEP], like the model sees it

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Unit-length float32 vectors, one row per text."""
        with self._lock:  # PyTorch already uses every core; serialise callers
            vectors = self._engine.encode(texts, batch_size=settings.embedding_batch_size, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Queries get the model's retrieval instruction; documents don't (per BGE usage notes)."""
        query = f"{self.query_prefix} {text}" if self.query_prefix else text
        return self.embed_documents([query])[0]


_instance: Embedder | None = None


def get_embedder() -> Embedder:
    global _instance
    if _instance is None:
        _instance = Embedder()
    return _instance
