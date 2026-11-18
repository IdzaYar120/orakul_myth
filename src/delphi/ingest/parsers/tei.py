from pathlib import Path

from pydantic import BaseModel


class ParsedSection(BaseModel):
    work: str
    author: str
    ref: str
    text: str


def parse_tei_xml(file_path: Path) -> list[ParsedSection]:
    """Parse Perseus TEI XML preserving book/chapter/paragraph structure."""
    return []
