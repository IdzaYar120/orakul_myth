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
    """Hybrid search: dense (Chroma BGE-M3) + sparse (BM25) via Reciprocal Rank Fusion (RRF)."""

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
        # Stage 0: return empty list or mock data for skeleton verification;
        # full index is populated in Stage 3.
        return []
