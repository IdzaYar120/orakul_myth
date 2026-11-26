"""Cross-encoder reranker (BAAI/bge-reranker-v2-m3).

Re-scores the best fused candidates against the (English) question and keeps the best
`top_k`. Passages below `min_relevance` are dropped; if nothing is left, the oracle refuses
before generating ("the sources are silent").

Measured on the golden set (stage 4): with the English query and a 0.05 threshold it refuses
5 of 8 trap questions and loses 3 of 72 answerable ones; with the Ukrainian query its scores are
too low to be useful. Disabled by default (RERANK_ENABLED): ~7.5 s per question on CPU.
"""

import math
from typing import Any

from delphi.config import settings
from delphi.rag.retriever import RetrievedPassage


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class Reranker:
    def __init__(
        self,
        model_name: str | None = None,
        min_relevance: float | None = None,
        enabled: bool | None = None,
        model: Any = None,
    ):
        self.model_name = model_name or settings.reranker_model
        self.min_relevance = min_relevance if min_relevance is not None else settings.min_relevance
        self.enabled = settings.rerank_enabled if enabled is None else enabled
        self._model = model

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device=settings.embedding_device)
        return self._model

    def score(self, query: str, passages: list[RetrievedPassage]) -> list[float]:
        raw = self._load().predict([(query, p.text) for p in passages])
        scores = [float(s) for s in raw]
        # Some cross-encoders return logits; map them to 0..1 so the threshold is stable
        if any(s < 0.0 or s > 1.0 for s in scores):
            scores = [_sigmoid(s) for s in scores]
        return scores

    def rerank(
        self, query: str, passages: list[RetrievedPassage], top_k: int = 5
    ) -> list[RetrievedPassage]:
        if not passages or not self.enabled:
            return passages[:top_k]
        scored = sorted(
            zip(self.score(query, passages), passages, strict=True),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [
            p.model_copy(update={"score": s}) for s, p in scored[:top_k] if s >= self.min_relevance
        ]
