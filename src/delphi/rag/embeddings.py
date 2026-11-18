"""Text embeddings: BAAI/bge-m3 via sentence-transformers, or a hashing stand-in for tests."""

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from delphi.config import settings

_WORD = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Multilingual dense embeddings (a Ukrainian question finds English passages)."""

    def __init__(self, model_name: str | None = None, device: str | None = None):
        from sentence_transformers import SentenceTransformer

        self.name = model_name or settings.embedding_model
        self._model = SentenceTransformer(self.name, device=device or settings.embedding_device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 50,
        )
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class HashingEmbedder:
    """Deterministic bag-of-words hashing vectors: no model download (tests, CI)."""

    def __init__(self, dim: int = 256):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@lru_cache(maxsize=2)
def get_embedder(model_name: str | None = None) -> Embedder:
    name = model_name or settings.embedding_model
    if name.startswith("hashing"):
        return HashingEmbedder()
    return SentenceTransformerEmbedder(name)
