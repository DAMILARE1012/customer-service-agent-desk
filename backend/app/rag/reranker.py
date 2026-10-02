"""Cross-encoder reranking: reads the query and each candidate chunk together, so it judges relevance
far better than comparing two independently made vectors — at the cost of one model pass per pair, which
is why it only reorders the top RERANK_CANDIDATES of the hybrid ranking. One process-wide instance.
"""

import threading
from functools import cached_property

import numpy as np

from app.config import settings


class Reranker:
    def __init__(self, model: str):
        self.model = model
        self._lock = threading.Lock()

    @cached_property
    def _engine(self):
        from sentence_transformers import CrossEncoder

        # sentence-transformers 6.1 warns that cache_folder is deprecated, but its suggested per-component
        # cache_dir crashes (passed twice to AutoConfig). Keep cache_folder until that's fixed upstream.
        return CrossEncoder(self.model, cache_folder=str(settings.models_path), device="cpu", max_length=512)

    def score(self, query: str, passages: list[str]) -> np.ndarray:
        """Relevance of each passage to the query, 0–1 (sigmoid of the model's logit); higher is better."""
        if not passages:
            return np.zeros(0, dtype=np.float32)
        import torch

        with self._lock:  # PyTorch already uses every core; serialise callers
            # Explicit sigmoid: some checkpoints (ms-marco) default to raw logits, others (bge) to sigmoid.
            scores = self._engine.predict(
                [(query, p) for p in passages], batch_size=32, show_progress_bar=False, activation_fn=torch.nn.Sigmoid()
            )
        return np.asarray(scores, dtype=np.float32)

    def warm_up(self) -> None:
        self.score("warm up", ["warm up"])


_instance: Reranker | None = None


def get_reranker() -> Reranker | None:
    """The configured reranker, or None when RERANKER_MODEL is empty."""
    global _instance
    if not settings.reranker_model:
        return None
    if _instance is None or _instance.model != settings.reranker_model:
        _instance = Reranker(settings.reranker_model)
    return _instance
