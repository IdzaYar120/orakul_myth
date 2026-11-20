"""Project Gutenberg plain-text parser (Apollonius' Argonautica, tr. Seaton).

The Gutenberg text has no line numbers, only ``BOOK I`` .. ``BOOK IV`` headings and paragraphs
separated by blank lines. Every paragraph becomes a section with ref ``"1§12"`` (book 1,
paragraph 12) — deliberately not "1.12", which would read as a verse line of the original.
Everything before the first ``BOOK`` heading after the ``*** START`` marker (title page,
contents, introduction) and after ``*** END`` (licence) is dropped. Footnotes ("[5]" in the
text, "5 God of embarcation." after the last book) go to ``notes``, as in the TEI parser.
"""

import re
from pathlib import Path

from delphi.ingest.parsers.tei import ParsedSection

_START = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG", re.M)
_END = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", re.M)
_BOOK = re.compile(r"^BOOK ([IVXLC]+)$")
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_WS = re.compile(r"\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_NOTE_MARK = re.compile(r"\[(\d+)\]")
_NOTE_BODY = re.compile(r"^(\d{1,3}) (\S.*)$")
_TRAILER = re.compile(r"^(End of (the )?Project Gutenberg|ENDNOTES:?$|FOOTNOTES:?$)", re.I)


def roman_to_int(numeral: str) -> int:
    total = 0
    for i, ch in enumerate(numeral):
        value = _ROMAN[ch]
        nxt = _ROMAN[numeral[i + 1]] if i + 1 < len(numeral) else 0
        total += -value if value < nxt else value
    return total


def _body(text: str) -> str:
    start = _START.search(text)
    if start:
        text = text[text.find("\n", start.end()) + 1 :]
    end = _END.search(text)
    return text[: end.start()] if end else text


def parse_gutenberg_text(file_path: Path, work: str = "", author: str = "") -> list[ParsedSection]:
    """Paragraphs of every BOOK as sections with refs "<book>§<paragraph>"."""
    raw = file_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    lines = _body(raw).split("\n")

    headings: list[tuple[int, int]] = []  # (line index, book number)
    for i, line in enumerate(lines):
        m = _BOOK.match(line.strip())
        if m:
            headings.append((i, roman_to_int(m[1])))
    if not headings:
        raise ValueError(f"{file_path.name}: no 'BOOK ...' headings")
    # The table of contents repeats the headings; the text starts at the last "BOOK I"
    first = max(k for k, (_, number) in enumerate(headings) if number == 1)
    headings = headings[first:]

    books: list[tuple[int, list[str]]] = []
    footnotes: dict[str, str] = {}
    for k, (start, number) in enumerate(headings):
        stop = headings[k + 1][0] if k + 1 < len(headings) else len(lines)
        paragraphs: list[str] = []
        for chunk in _PARAGRAPH_BREAK.split("\n".join(lines[start + 1 : stop])):
            paragraph = _WS.sub(" ", chunk).strip()
            if not paragraph or _TRAILER.match(paragraph):
                continue
            note = _NOTE_BODY.match(paragraph)
            if note:  # the footnotes block follows the last book
                footnotes[note[1]] = note[2]
            else:
                paragraphs.append(paragraph)
        books.append((number, paragraphs))

    sections: list[ParsedSection] = []
    for number, paragraphs in books:
        for n, paragraph in enumerate(paragraphs, 1):
            marks = _NOTE_MARK.findall(paragraph)
            text = _WS.sub(" ", _NOTE_MARK.sub("", paragraph)).strip()
            sections.append(
                ParsedSection(
                    work=work,
                    author=author,
                    ref=f"{number}§{n}",
                    text=text,
                    notes=[footnotes[m] for m in marks if m in footnotes],
                )
            )
    return sections
