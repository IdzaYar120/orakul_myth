"""Write chunks to SQLite (source of truth), Chroma (dense vectors) and BM25 (lexical).

Idempotent: chunk ids are stable hashes; unchanged chunks are not re-embedded, chunks that
disappeared from a re-ingested source are removed from all three stores.
"""

import hashlib
import json
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, delete, select

from delphi.db.models import Passage, PassageEntity
from delphi.ingest.chunker import Chunk
from delphi.rag.embeddings import Embedder

COLLECTION = "passages"
BM25_FILE = "bm25.pkl"
CHROMA_DIR = "chroma"
_TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have he her his i in is it its of on or "
    "she so that the their them then there they this to was were which who with".split()
)


def bm25_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


@dataclass
class IndexStats:
    passages: int = 0
    embedded: int = 0
    removed: int = 0
    tagged: int = 0


def open_collection(index_dir: Path, create: bool = True) -> Any:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.PersistentClient(
        path=str(index_dir / CHROMA_DIR),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    if create:
        return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    return client.get_collection(COLLECTION)


def build_indexes(
    chunks: list[Chunk],
    tags: dict[str, list[str]],
    session: Session,
    index_dir: Path,
    embedder: Embedder,
    source_ids: set[str],
    batch_size: int = 32,
) -> IndexStats:
    """Replace the indexed content of `source_ids` with `chunks`."""
    stats = IndexStats()
    index_dir.mkdir(parents=True, exist_ok=True)
    new_ids = {c.id for c in chunks}

    # 1. SQLite: passages + passage_entity
    stale = session.exec(
        select(Passage.id).where(
            col(Passage.source_id).in_(source_ids), col(Passage.id).not_in(new_ids)
        )
    ).all()
    if stale:
        session.exec(delete(PassageEntity).where(col(PassageEntity.passage_id).in_(stale)))  # type: ignore[call-overload]
        session.exec(delete(Passage).where(col(Passage.id).in_(stale)))  # type: ignore[call-overload]
        stats.removed = len(stale)
    for c in chunks:
        session.merge(
            Passage(
                id=c.id,
                source_id=c.source_id,
                work=c.work,
                author=c.author,
                translator=c.translator,
                ref=c.ref,
                text=c.text,
                n_tokens=c.n_tokens,
                notes_json=json.dumps(c.notes, ensure_ascii=False) if c.notes else None,
            )
        )
    if new_ids:
        session.exec(delete(PassageEntity).where(col(PassageEntity.passage_id).in_(new_ids)))  # type: ignore[call-overload]
    for cid, entity_ids in tags.items():
        for eid in entity_ids:
            session.add(PassageEntity(passage_id=cid, entity_id=eid))
    session.commit()
    stats.passages = len(chunks)
    stats.tagged = sum(1 for ids in tags.values() if ids)

    # 2. Chroma: embed only new or changed chunks
    collection = open_collection(index_dir)
    if stale:
        collection.delete(ids=list(stale))
    existing: dict[str, str] = {}
    if new_ids:
        got = collection.get(ids=list(new_ids), include=["metadatas"])
        for cid, meta in zip(got["ids"], got["metadatas"] or [], strict=False):
            existing[cid] = (meta or {}).get("text_hash", "")
    todo = [
        c for c in chunks if existing.get(c.id) != text_hash(c.text) or existing.get(c.id) is None
    ]
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embedder.embed_documents([c.text for c in batch]),
            metadatas=[
                {
                    "passage_id": c.id,
                    "source_id": c.source_id,
                    "work": c.work,
                    "author": c.author,
                    "ref": c.ref,
                    "translator": c.translator,
                    # Chroma metadata cannot hold lists
                    "entities": ",".join(tags.get(c.id, [])),
                    "text_hash": text_hash(c.text),
                    "embedder": embedder.name,
                }
                for c in batch
            ],
        )
    # Entity tags can change without text changes (new aliases): refresh metadata
    unchanged = [c for c in chunks if c not in todo]
    for i in range(0, len(unchanged), 256):
        batch = unchanged[i : i + 256]
        collection.update(
            ids=[c.id for c in batch],
            metadatas=[{"entities": ",".join(tags.get(c.id, []))} for c in batch],
        )
    stats.embedded = len(todo)

    # 3. BM25 over every passage in SQLite
    rebuild_bm25(session, index_dir)
    return stats


def rebuild_bm25(session: Session, index_dir: Path) -> int:
    rows = session.exec(select(Passage.id, Passage.text)).all()
    payload = {"ids": [r[0] for r in rows], "tokens": [bm25_tokens(r[1]) for r in rows]}
    with open(index_dir / BM25_FILE, "wb") as f:
        pickle.dump(payload, f)
    return len(rows)
