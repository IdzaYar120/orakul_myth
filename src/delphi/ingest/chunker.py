"""Structure-aware chunking (not by characters).

* structured prose (Apollodorus): one chunk per section; neighbouring small sections are
  merged, oversized sections are split at sentence boundaries;
* line-numbered blocks (Hesiod, Homer): consecutive blocks are grouped to the target size
  (~20–30 verse lines) with an overlap of one block.

The chunk ``ref`` is a range ("Apollod. 1.1.1–1.1.3", "Hes. Theog. 1–21"), its id is a hash of
source + ref, so re-ingesting the same text is idempotent.
"""

import hashlib
import re

from pydantic import BaseModel, Field

from delphi.ingest.parsers.tei import ParsedSection
from delphi.ingest.sources import Source

TARGET_TOKENS = 400
MIN_TOKENS = 150
MAX_TOKENS = 600
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\"'“‘(])")


class Chunk(BaseModel):
    id: str  # hash(source id + ref)
    source_id: str
    work: str
    author: str
    translator: str
    ref: str  # display reference with prefix, e.g. "Apollod. 1.1.1–1.1.3"
    ref_start: str  # structural ref of the first unit, e.g. "1.1.1" or "1"
    ref_end: str
    unit_refs: list[str] = Field(default_factory=list)
    text: str
    notes: list[str] = Field(default_factory=list)
    n_tokens: int


def count_tokens(text: str) -> int:
    """Rough token estimate (~1.3 tokens per English word); no tokenizer dependency."""
    return int(len(text.split()) * 1.3) + 1


def chunk_id(source_id: str, ref: str) -> str:
    return hashlib.sha1(f"{source_id}|{ref}".encode()).hexdigest()[:16]


def _make_chunk(source: Source, units: list[ParsedSection], text: str | None = None) -> Chunk:
    start, end = units[0].ref, units[-1].ref
    ref = source.format_ref(start, end)
    body = text if text is not None else " ".join(u.text for u in units)
    return Chunk(
        id=chunk_id(source.id, ref),
        source_id=source.id,
        work=units[0].work or source.title,
        author=units[0].author or source.author,
        translator=source.translator,
        ref=ref,
        ref_start=start,
        ref_end=end,
        unit_refs=[u.ref for u in units],
        text=body,
        notes=[n for u in units for n in u.notes],
        n_tokens=count_tokens(body),
    )


def _split_long(source: Source, unit: ParsedSection, max_tokens: int) -> list[Chunk]:
    """Split an oversized section at sentence boundaries; parts share the section ref."""
    sentences = _SENTENCE_END.split(unit.text)
    parts: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if current and count_tokens(" ".join([*current, sentence])) > max_tokens:
            parts.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        parts.append(" ".join(current))
    if len(parts) == 1:
        return [_make_chunk(source, [unit])]
    chunks = []
    for i, part in enumerate(parts, 1):
        chunk = _make_chunk(source, [unit], text=part)
        ref = f"{source.format_ref(unit.ref)} ({i}/{len(parts)})"
        chunks.append(
            chunk.model_copy(update={"ref": ref, "id": chunk_id(source.id, ref), "notes": []})
        )
    chunks[0].notes = unit.notes
    return chunks


def _chunk_prose(
    source: Source, sections: list[ParsedSection], min_tokens: int, max_tokens: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer: list[ParsedSection] = []

    def flush() -> None:
        if buffer:
            chunks.append(_make_chunk(source, list(buffer)))
            buffer.clear()

    for section in sections:
        tokens = count_tokens(section.text)
        if tokens > max_tokens:
            flush()
            chunks.extend(_split_long(source, section, max_tokens))
            continue
        merged = count_tokens(" ".join(u.text for u in [*buffer, section]))
        if buffer and merged > max_tokens:
            flush()
        buffer.append(section)
        if count_tokens(" ".join(u.text for u in buffer)) >= min_tokens:
            flush()
    flush()
    return chunks


def _book(ref: str) -> str:
    """'13.328' -> '13' (Homer); '453' -> '' (Hesiod: a single run of lines)."""
    return ref.rpartition(".")[0]


def _chunk_lines(
    source: Source, blocks: list[ParsedSection], target_tokens: int, overlap: int
) -> list[Chunk]:
    """Group consecutive line blocks; a chunk never crosses a book boundary."""
    chunks: list[Chunk] = []
    i = 0
    while i < len(blocks):
        group: list[ParsedSection] = []
        j = i
        while (
            j < len(blocks)
            and (not group or count_tokens(" ".join(b.text for b in group)) < target_tokens)
            and (not group or _book(blocks[j].ref) == _book(group[0].ref))
        ):
            group.append(blocks[j])
            j += 1
        chunks.append(_make_chunk(source, group))
        if j >= len(blocks):
            break
        new_book = _book(blocks[j].ref) != _book(group[0].ref)
        i = j if new_book else max(j - overlap, i + 1)
    return chunks


def chunk_sections(
    sections: list[ParsedSection],
    source: Source,
    target_tokens: int = TARGET_TOKENS,
    min_tokens: int = MIN_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap: int = 1,
) -> list[Chunk]:
    """Chunk parsed sections of one source (300–600 tokens per chunk)."""
    if not sections:
        return []
    if sections[0].kind == "lines":
        return _chunk_lines(source, sections, target_tokens, overlap)
    return _chunk_prose(source, sections, min_tokens, max_tokens)
