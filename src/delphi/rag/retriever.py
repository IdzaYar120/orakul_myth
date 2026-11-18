from pydantic import BaseModel


class RetrievedPassage(BaseModel):
    id: str
    work: str
    author: str
    translator: str
    ref: str
    text: str
    score: float = 0.0
    entity_ids: list[str] = []


class HybridRetriever:
    """
    Гібридний пошук: щільний (Chroma BGE-M3) + розріджений (BM25)
    через Reciprocal Rank Fusion (RRF).
    """

    def __init__(self, k_dense: int = 20, k_sparse: int = 20, rrf_k: int = 60):
        self.k_dense = k_dense
        self.k_sparse = k_sparse
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        boost_entity_ids: list[str] | None = None,
        top_k: int = 10,
    ) -> list[RetrievedPassage]:
        # У Етапі 0 повертаємо пустий список або мок-дані для перевірки каркасу,
        # повноцінний індекс наповнюється на Етапі 3
        return []
