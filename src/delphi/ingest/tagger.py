from sqlmodel import Session

from delphi.ingest.chunker import Chunk


def tag_entities_in_chunks(
    chunks: list[Chunk], session: Session | None = None
) -> dict[str, list[str]]:
    """Пошук англійських аліасів сутностей у тексті чанків."""
    return {}
