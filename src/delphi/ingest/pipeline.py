"""Offline ingest: download -> parse -> chunk -> tag entities -> index (`delphi ingest`)."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from delphi.config import settings
from delphi.db.repo import engine, init_db
from delphi.ingest.chunker import Chunk, chunk_sections
from delphi.ingest.download import download_source
from delphi.ingest.indexer import IndexStats, build_indexes
from delphi.ingest.parsers.gutenberg import parse_gutenberg_text
from delphi.ingest.parsers.tei import ParsedSection, parse_tei_xml
from delphi.ingest.sources import Source, load_sources, select_sources
from delphi.ingest.tagger import EntityTagger
from delphi.rag.embeddings import Embedder, get_embedder


@dataclass
class SourceReport:
    source_id: str
    sections: int
    chunks: int
    avg_tokens: int
    tagged: int


def parse_source(source: Source, path: Path) -> list[ParsedSection]:
    if source.format == "tei_xml":
        return parse_tei_xml(path, work=source.title, author=source.author)
    if source.format == "gutenberg_text":
        return parse_gutenberg_text(path, work=source.title, author=source.author)
    raise NotImplementedError(f"{source.id}: формат {source.format} ще не підтримується")


def run_ingest(
    source_ids: list[str] | None = None,
    force_download: bool = False,
    embedder: Embedder | None = None,
    index_dir: Path | None = None,
    engine_override=None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[SourceReport], IndexStats]:
    eng = engine_override or engine
    init_db(eng)
    sources = select_sources(load_sources(), source_ids)
    if not sources:
        raise ValueError("Немає увімкнених джерел (enabled: true у data/sources.yaml)")

    all_chunks: list[Chunk] = []
    reports: list[SourceReport] = []
    for source in sources:
        progress(f"{source.id}: завантаження")
        sections = []
        chunks = []
        for view, filename in source.files():  # several files for e.g. the Homeric Hymns
            path = download_source(view, force=force_download, filename=filename)
            part_sections = parse_source(view, path)
            sections.extend(part_sections)
            chunks.extend(chunk_sections(part_sections, view))
        all_chunks.extend(chunks)
        reports.append(
            SourceReport(
                source_id=source.id,
                sections=len(sections),
                chunks=len(chunks),
                avg_tokens=sum(c.n_tokens for c in chunks) // max(len(chunks), 1),
                tagged=0,
            )
        )
        progress(f"{source.id}: {len(sections)} розділів -> {len(chunks)} чанків")

    with Session(eng) as session:
        tagger = EntityTagger.from_db(session)
        tags = tagger.tag_chunks(all_chunks)
        for report in reports:
            report.tagged = sum(
                1 for c in all_chunks if c.source_id == report.source_id and tags.get(c.id)
            )
        progress("ембеддинги та індекси (перший запуск завантажує модель)")
        stats = build_indexes(
            all_chunks,
            tags,
            session,
            index_dir or settings.index_dir,
            embedder or get_embedder(),
            source_ids={s.id for s in sources},
        )
    return reports, stats
