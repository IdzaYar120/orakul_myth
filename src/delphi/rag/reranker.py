from delphi.config import settings
from delphi.rag.retriever import RetrievedPassage


class Reranker:
    """
    Cross-encoder reranker (e.g., BAAI/bge-reranker-v2-m3).
    Filters out results with relevance below the threshold (min_relevance).
    """

    def __init__(self, model_name: str | None = None, min_relevance: float | None = None):
        self.model_name = model_name or settings.reranker_model
        self.min_relevance = min_relevance if min_relevance is not None else settings.min_relevance
        self.enabled = settings.rerank_enabled

    def rerank(
        self, query: str, passages: list[RetrievedPassage], top_k: int = 5
    ) -> list[RetrievedPassage]:
        if not passages or not self.enabled:
            return passages[:top_k]

        # CrossEncoder is loaded in subsequent stages
        # If top score is below threshold, return empty list
        return passages[:top_k]
