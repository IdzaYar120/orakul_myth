"""Tag entities mentioned in English chunks by dictionary lookup of their aliases.

Only English/Latin aliases are used (the corpus is English). Matching uses word boundaries:
* short names and translators' personifications ("Night", "Earth", "Sky" as gods) are matched
  case-sensitively, so ordinary lower-case words are not tagged;
* longer proper names (5+ letters) also match in lower case ("the Lernaean hydra").
Aliases that belong to several entities are ambiguous (e.g. "Ajax") and are skipped.
"""

import re
from collections import defaultdict
from collections.abc import Iterable

from sqlmodel import Session, col, select

from delphi.db.models import Alias
from delphi.ingest.chunker import Chunk

MIN_ALIAS_LEN = 3
CASE_INSENSITIVE_MIN_LEN = 5
# Aliases that are also ordinary English words: only the capitalised form names the god
COMMON_WORDS = frozenset(
    "earth sky heaven night day darkness love strife death sleep victory fates furies muses "
    "ocean sun ether hope sea chaos graces hours fortune justice dawn panic fear dread".split()
)


def _pattern(forms: Iterable[str], flags: int = 0) -> re.Pattern[str] | None:
    ordered = sorted(forms, key=len, reverse=True)  # longest match first
    if not ordered:
        return None
    body = "|".join(re.escape(f) for f in ordered)
    return re.compile(r"(?<![\w-])(" + body + r")(?![\w-])", flags)


class EntityTagger:
    def __init__(self, aliases: dict[str, str]):
        """aliases: surface form -> entity id (unambiguous forms only)."""
        self.aliases = aliases
        self._lower = {
            a.lower(): eid
            for a, eid in aliases.items()
            if len(a) >= CASE_INSENSITIVE_MIN_LEN and a.lower() not in COMMON_WORDS
        }
        self._pattern = _pattern(aliases)
        self._pattern_ci = _pattern(self._lower, re.IGNORECASE)

    @classmethod
    def from_db(cls, session: Session) -> "EntityTagger":
        rows = session.exec(select(Alias).where(col(Alias.lang).in_(["en", "la"]))).all()
        return cls.from_pairs((a.alias, a.entity_id) for a in rows)

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[str, str]]) -> "EntityTagger":
        owners: dict[str, set[str]] = defaultdict(set)
        for alias, entity_id in pairs:
            alias = alias.strip()
            if len(alias) < MIN_ALIAS_LEN or not alias[0].isupper():
                continue
            owners[alias].add(entity_id)
        return cls({a: next(iter(ids)) for a, ids in owners.items() if len(ids) == 1})

    def tag_text(self, text: str) -> list[str]:
        found: set[str] = set()
        if self._pattern is not None:
            found |= {self.aliases[m.group(1)] for m in self._pattern.finditer(text)}
        if self._pattern_ci is not None:
            found |= {self._lower[m.group(1).lower()] for m in self._pattern_ci.finditer(text)}
        return sorted(found)

    def tag_chunks(self, chunks: list[Chunk]) -> dict[str, list[str]]:
        return {c.id: self.tag_text(c.text) for c in chunks}


def tag_entities_in_chunks(chunks: list[Chunk], session: Session) -> dict[str, list[str]]:
    """chunk id -> entity ids mentioned in the chunk."""
    return EntityTagger.from_db(session).tag_chunks(chunks)
