"""Perseus TEI XML parser.

Two layouts occur in the Perseus English translations:

* structured prose (Apollodorus): nested ``<div type="textpart" subtype="book|chapter|section"
  n="...">``; every leaf div becomes a section with ref "1.1.1";
* line-numbered prose (Hesiod, Homeric Hymns): ``<l n="453">`` blocks inside the translation
  div; every block becomes a section with ref "453" (the line of the original where it starts);
* "cards" with line milestones (Homer, Murray): ``<div subtype="book"><div subtype="card"
  n="33">`` with ``<milestone unit="line" n="35"/>`` every ~5 lines; each card is cut at its
  milestones into line-numbered pieces with refs "1.33", "1.35", ... so citations stay exact.

Translator's notes (``<note>``) are moved to a separate field so they neither pollute
the embeddings nor appear as the ancient author's words.
"""

import re
from pathlib import Path

from lxml import etree
from pydantic import BaseModel, Field

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI_NS}
_WS = re.compile(r"\s+")
# Skipped entirely: notes (collected separately), editorial apparatus, page breaks
_SKIP_TAGS = {f"{{{TEI_NS}}}note", f"{{{TEI_NS}}}bibl", f"{{{TEI_NS}}}pb"}
_MILESTONE = f"{{{TEI_NS}}}milestone"
# Private-use markers left in the collected text where a line milestone / a note stood
_LINE_MARK = ""
_NOTE_MARK = ""
_MARKS = re.compile("([])([^]*?)")


class ParsedSection(BaseModel):
    work: str
    author: str
    ref: str
    text: str
    notes: list[str] = Field(default_factory=list)
    kind: str = "prose"  # prose (structured sections) | lines (line-numbered blocks)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _collect(
    el: etree._Element, text_parts: list[str], notes: list[str], marks: bool = False
) -> None:
    """Text of `el` without notes; notes go to `notes`. Tails are always kept.

    With ``marks``, line milestones and notes leave a marker in the text so the caller can
    cut the text at the milestones and attach each note to its piece.
    """
    if el.text:
        text_parts.append(el.text)
    for child in el:
        removed = False
        if not isinstance(child.tag, str):  # comments, processing instructions
            pass
        elif child.tag == f"{{{TEI_NS}}}note":
            note = _clean("".join(child.itertext()))
            if note:
                if marks:
                    text_parts.append(f"{_NOTE_MARK}{len(notes)}")
                notes.append(note)
            removed = True
        elif marks and child.tag == _MILESTONE and child.get("unit") == "line":
            text_parts.append(f" {_LINE_MARK}{child.get('n', '')} ")
        elif child.tag not in _SKIP_TAGS:
            _collect(child, text_parts, notes, marks)
        else:
            removed = True
        if child.tail:
            # A note anchored between two words ("Aether<note/>and Day") must not glue them
            previous = text_parts[-1] if text_parts else ""
            if removed and previous[-1:].isalnum() and child.tail[:1].isalnum():
                text_parts.append(" ")
            text_parts.append(child.tail)


def _text_and_notes(el: etree._Element) -> tuple[str, list[str]]:
    parts: list[str] = []
    notes: list[str] = []
    _collect(el, parts, notes)
    return _clean("".join(parts)), notes


def _split_at_lines(div: etree._Element, book: str, card: str) -> list[tuple[str, str, list[str]]]:
    """Cut a Homer card at its line milestones: [(ref "book.line", text, notes), ...]."""
    parts: list[str] = []
    notes: list[str] = []
    _collect(div, parts, notes, marks=True)
    pieces: list[tuple[str, list[str], list[str]]] = [(card, [], [])]
    pos = 0
    raw = "".join(parts)
    for m in _MARKS.finditer(raw):
        pieces[-1][1].append(raw[pos : m.start()])
        if m[1] == _LINE_MARK:
            pieces.append((m[2], [], []))
        else:
            pieces[-1][2].append(notes[int(m[2])])
        pos = m.end()
    pieces[-1][1].append(raw[pos:])
    out = []
    for line, texts, piece_notes in pieces:
        text = _clean("".join(texts))
        if text:
            out.append((f"{book}.{line}", text, piece_notes))
        elif piece_notes and out:
            out[-1][2].extend(piece_notes)
    return out


def _translation_div(root: etree._Element) -> etree._Element:
    div = root.find(".//t:body/t:div[@type='translation']", NS)
    if div is None:
        div = root.find(".//t:body/t:div", NS)
    if div is None:
        raise ValueError("TEI: no <div> in <body>")
    return div


def _is_textpart(el: etree._Element) -> bool:
    """A numbered structural division. Unnumbered ones (the two halves of the Hymn to Apollo)
    carry no reference, so their ``<l n>`` lines are used instead."""
    return bool(el.tag == f"{{{TEI_NS}}}div" and el.get("type") == "textpart" and el.get("n"))


def parse_tei_xml(file_path: Path, work: str = "", author: str = "") -> list[ParsedSection]:
    """Parse a Perseus TEI file into ordered sections with structural references."""
    root = etree.parse(str(file_path)).getroot()
    if not work:
        work = _clean(root.findtext(".//t:titleStmt/t:title", default="", namespaces=NS))
    if not author:
        author = _clean(root.findtext(".//t:titleStmt/t:author", default="", namespaces=NS))
    body = _translation_div(root)

    sections: list[ParsedSection] = []
    textparts = [d for d in body.iter(f"{{{TEI_NS}}}div") if _is_textpart(d)]
    if textparts:
        for div in textparts:
            if any(_is_textpart(c) for c in div):
                continue  # not a leaf
            ref_parts = [
                a.get("n", "") for a in reversed(list(div.iterancestors())) if _is_textpart(a)
            ]
            if (
                div.get("subtype") == "card"
                and div.find(f".//{_MILESTONE}[@unit='line']") is not None
            ):
                for ref, text, notes in _split_at_lines(div, ".".join(ref_parts), div.get("n", "")):
                    sections.append(
                        ParsedSection(
                            work=work, author=author, ref=ref, text=text, notes=notes, kind="lines"
                        )
                    )
                continue
            ref = ".".join([*ref_parts, div.get("n", "")])
            text, notes = _text_and_notes(div)
            if text:
                sections.append(
                    ParsedSection(work=work, author=author, ref=ref, text=text, notes=notes)
                )
        return sections

    for line in body.iter(f"{{{TEI_NS}}}l"):
        text, notes = _text_and_notes(line)
        if text:
            sections.append(
                ParsedSection(
                    work=work,
                    author=author,
                    ref=line.get("n", ""),
                    text=text,
                    notes=notes,
                    kind="lines",
                )
            )
    return sections
