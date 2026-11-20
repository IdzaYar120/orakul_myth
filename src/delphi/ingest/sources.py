"""Typed access to data/sources.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from delphi.config import settings


class SourcePart(BaseModel):
    """One file of a multi-file work (e.g. a single Homeric Hymn)."""

    id: str
    title: str
    download_url: str
    ref_prefix: str


class Source(BaseModel):
    id: str
    author: str
    title: str
    work_uk: str | None = None
    translator: str
    year: int | None = None
    ref_prefix: str
    license: str
    translation_license: str | None = None
    encoding_license: str | None = None
    url: str
    download_url: str | None = None
    format: str  # tei_xml | gutenberg_text
    stage: int = 3
    enabled: bool = False
    notes: str | None = None
    parts: list[SourcePart] = Field(default_factory=list)

    @property
    def raw_filename(self) -> str:
        ext = ".xml" if self.format == "tei_xml" else ".txt"
        return f"{self.id}{ext}"

    def as_part(self, part: SourcePart) -> "Source":
        """The same source (same id) restricted to one file, with that file's prefix and title."""
        return self.model_copy(
            update={
                "title": part.title,
                "ref_prefix": part.ref_prefix,
                "download_url": part.download_url,
                "parts": [],
            }
        )

    def files(self) -> list[tuple["Source", str]]:
        """(source view, local raw filename) for every file of this source."""
        if not self.parts:
            return [(self, self.raw_filename)]
        ext = ".xml" if self.format == "tei_xml" else ".txt"
        return [(self.as_part(p), f"{self.id}__{p.id}{ext}") for p in self.parts]

    def format_ref(self, start: str, end: str | None = None) -> str:
        """'Apollod. 1.1.1', 'Apollod. 1.1.1–1.1.3', 'Hes. Theog. 1–21'."""
        if end is None or end == start:
            return f"{self.ref_prefix} {start}"
        return f"{self.ref_prefix} {start}–{end}"


def load_sources(path: Path | None = None) -> list[Source]:
    src_file = path or settings.data_dir / "sources.yaml"
    with open(src_file, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [Source(**s) for s in data.get("sources", [])]


def select_sources(sources: list[Source], ids: list[str] | None = None) -> list[Source]:
    """Explicit ids (enabled or not), otherwise every enabled source."""
    if ids:
        by_id = {s.id: s for s in sources}
        unknown = [i for i in ids if i not in by_id]
        if unknown:
            raise ValueError(f"Невідомі джерела: {', '.join(unknown)}")
        return [by_id[i] for i in ids]
    return [s for s in sources if s.enabled]
