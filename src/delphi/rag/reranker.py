from delphi.config import settings
from delphi.rag.retriever import RetrievedPassage


class Reranker:
    """
    Реранкер на базі cross-encoder (наприклад, BAAI/bge-reranker-v2-m3).
    Відсікає результати з релевантністю нижче порога (min_relevance).
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

        # Під час наступних етапів тут завантажується CrossEncoder
        # Якщо скор найвищого уривка нижче порога, повертаємо порожній список
        return passages[:top_k]
