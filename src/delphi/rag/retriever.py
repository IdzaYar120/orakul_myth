"""Hybrid retrieval: dense (Chroma + bge-m3) and lexical (BM25), fused with Reciprocal Rank
Fusion; chunks mentioning entities linked in the question get a soft boost.

With an English translation of the question (the corpus is English) three rankings are fused:
dense(English), dense(Ukrainian + English names) and BM25(English). Without it: dense and BM25
over the Ukrainian query with the English names. Measured on the golden set (stage 4,
`delphi eval`): the translation lifts Hit@5 61% -> 71%, Hit@20 78% -> 82%, MRR@20 50% -> 57%.
"""

import logging
import pickle
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from delphi.config import settings
from delphi.db.models import Passage, PassageEntity
from delphi.db.repo import engine
from delphi.ingest.indexer import BM25_FILE, CHROMA_DIR, bm25_tokens, open_collection
from delphi.rag.embeddings import Embedder, get_embedder

log = logging.getLogger(__name__)

# Genre prior: the mythographic handbook and Hesiod state myths directly, while Pausanias (half
# of all passages) mostly describes monuments and names the gods in passing. Mild on purpose.
SOURCE_PRIOR: dict[str, float] = {
    "apollodorus_library": 1.3,
    "hesiod_theogony": 1.2,
    "hesiod_works_and_days": 1.2,
    "homeric_hymns": 1.1,
    "pausanias_description_of_greece": 0.85,
}


class RetrievedPassage(BaseModel):
    id: str
    work: str
    author: str
    translator: str
    ref: str
    text: str
    score: float = 0.0
    entity_ids: list[str] = Field(default_factory=list)
    source_id: str | None = None
    notes: list[str] = Field(default_factory=list)


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]:
    """RRF: score(d) = sum over rankings of 1 / (k + rank(d)), rank starting at 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, 1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


class HybridRetriever:
    def __init__(
        self,
        k_dense: int = 20,
        k_sparse: int = 20,
        rrf_k: int = 60,
        entity_boost: float | None = None,
        index_dir: Path | None = None,
        embedder: Embedder | None = None,
        session: Session | None = None,
    ):
        self.k_dense = k_dense
        self.k_sparse = k_sparse
        self.rrf_k = rrf_k
        self.entity_boost = settings.entity_boost if entity_boost is None else entity_boost
        self.index_dir = index_dir or settings.index_dir
        self._embedder = embedder
        self._session = session
        self._collection: Any = None
        self._bm25: Any = None
        self._bm25_ids: list[str] = []
        self._bm25_mtime: float | None = None

    # ------------------------------------------------------------------ stores
    @property
    def available(self) -> bool:
        return (self.index_dir / BM25_FILE).exists() and (self.index_dir / CHROMA_DIR).exists()

    def _load_bm25(self) -> None:
        path = self.index_dir / BM25_FILE
        mtime = path.stat().st_mtime
        if self._bm25 is not None and self._bm25_mtime == mtime:
            return
        from rank_bm25 import BM25Okapi

        with open(path, "rb") as f:
            payload = pickle.load(f)
        self._bm25_ids = payload["ids"]
        self._bm25 = BM25Okapi(payload["tokens"]) if payload["tokens"] else None
        self._bm25_mtime = mtime

    def _dense(self, query: str) -> list[str]:
        if self._collection is None:
            self._collection = open_collection(self.index_dir, create=False)
        embedder = self._embedder or get_embedder()
        n = min(self.k_dense, max(self._collection.count(), 1))
        res = self._collection.query(query_embeddings=[embedder.embed_query(query)], n_results=n)
        return list(res["ids"][0]) if res["ids"] else []

    def _sparse(self, query: str) -> list[str]:
        self._load_bm25()
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(bm25_tokens(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [self._bm25_ids[i] for i in order[: self.k_sparse] if scores[i] > 0]

    def known_terms(self, terms: Iterable[str]) -> list[str]:
        """Expansion terms that occur in the corpus: Wikidata aliases such as "Aploun" or
        "Cape Matapan" only add noise to the query."""
        terms = list(terms)
        if not self.available:
            return terms
        self._load_bm25()
        if self._bm25 is None:
            return terms
        vocabulary = self._bm25.idf
        kept = []
        for term in terms:
            tokens = bm25_tokens(term)
            if tokens and all(t in vocabulary for t in tokens):
                kept.append(term)
        return kept

    # ------------------------------------------------------------------ retrieve
    def retrieve(
        self,
        query: str,
        boost_entity_ids: Iterable[str] | None = None,
        top_k: int = 10,
        query_en: str | None = None,
    ) -> list[RetrievedPassage]:
        if not self.available:
            log.warning("Search index not found in %s: run `delphi ingest`", self.index_dir)
            return []
        if query_en:
            rankings = [self._dense(query_en), self._dense(query), self._sparse(query_en)]
        else:
            rankings = [self._dense(query), self._sparse(query)]
        fused = reciprocal_rank_fusion(rankings, k=self.rrf_k)
        if not fused:
            return []

        with self._use_session() as session:
            ids = list(fused)
            rows = {p.id: p for p in session.exec(select(Passage).where(col(Passage.id).in_(ids)))}
            for pid in ids:
                if pid in rows:
                    fused[pid] *= SOURCE_PRIOR.get(rows[pid].source_id or "", 1.0)
            entities: dict[str, list[str]] = {}
            for pe in session.exec(
                select(PassageEntity).where(col(PassageEntity.passage_id).in_(ids))
            ).all():
                entities.setdefault(pe.passage_id, []).append(pe.entity_id)

            boost = set(boost_entity_ids or ())
            if boost:
                for pid in ids:
                    overlap = len(boost & set(entities.get(pid, [])))
                    if overlap:
                        fused[pid] *= 1 + self.entity_boost * min(overlap, 2)

            top = sorted(fused, key=lambda pid: fused[pid], reverse=True)[:top_k]
            return [
                RetrievedPassage(
                    id=pid,
                    work=rows[pid].work,
                    author=rows[pid].author,
                    translator=rows[pid].translator,
                    ref=rows[pid].ref,
                    text=rows[pid].text,
                    score=fused[pid],
                    entity_ids=sorted(entities.get(pid, [])),
                    source_id=rows[pid].source_id,
                    notes=rows[pid].notes,
                )
                for pid in top
                if pid in rows
            ]

    def _use_session(self) -> Any:
        if self._session is not None:
            from contextlib import nullcontext

            return nullcontext(self._session)
        return Session(engine)
