from pathlib import Path

from pydantic import BaseModel


class ParsedSection(BaseModel):
    work: str
    author: str
    ref: str
    text: str


def parse_tei_xml(file_path: Path) -> list[ParsedSection]:
    """Парсинг TEI XML Perseus зі збереженням структури книга/розділ/параграф."""
    return []
