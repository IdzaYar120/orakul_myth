from pydantic import BaseModel

from delphi.ingest.parsers.tei import ParsedSection


class Chunk(BaseModel):
    id: str  # hash(work + ref)
    work: str
    author: str
    translator: str
    ref: str
    text: str
    n_tokens: int


def chunk_sections(sections: list[ParsedSection], target_tokens: int = 400) -> list[Chunk]:
    """Structure-based chunking of text units (300-600 tokens)."""
    return []
