from sqlmodel import Session

from delphi.ingest.chunker import Chunk


def tag_entities_in_chunks(
    chunks: list[Chunk], session: Session | None = None
) -> dict[str, list[str]]:
    """Tag English entity aliases within text chunks."""
    return {}
