"""Entity linking for the oracle.

* Question -> entity ids (fuzzy over aliases, tolerant to Ukrainian case endings:
  "Ахілла", "Ахіллеса" -> achilles) + English names for query expansion.
* Answer text -> entity ids mentioned in it (for "open card / show on map" chips).
* Glossary of English -> Ukrainian names for the prompt.
"""

import re
from collections.abc import Callable, Iterable

from rapidfuzz import fuzz, process
from sqlmodel import Session, col, select

from delphi.db.models import Alias, Entity
from delphi.db.repo import engine

# Explicit Callable type: see the note in delphi.encyclopedia.search.
_RATIO: Callable[..., float] = fuzz.ratio
_WORD = re.compile(r"\b\w{3,}\b", flags=re.UNICODE)
LINK_SCORE = 80
MAX_EXPANSION_ALIASES = 3


def _stem(name: str) -> str:
    """Drop a final vowel/soft sign so that inflected forms match: Афіна -> Афін."""
    lowered = name.lower()
    if len(lowered) > 4 and lowered[-1] in "аяоеєиіїуюйь":
        return lowered[:-1]
    return lowered


class EntityLinker:
    def __init__(self, session: Session | None = None):
        self._session = session

    def _get_session(self) -> Session:
        return self._session or Session(engine)

    def _close(self, session: Session) -> None:
        if self._session is None:
            session.close()

    def extract_and_expand(self, question: str) -> tuple[list[str], list[str]]:
        """Entities mentioned in the question and English terms to add to the query."""
        session = self._get_session()
        try:
            aliases = session.exec(select(Alias)).all()
            if not aliases:
                return [], []
            alias_map: dict[str, str] = {a.alias.lower(): a.entity_id for a in aliases}
            names = list(alias_map)

            found: list[str] = []
            for word in _WORD.findall(question):
                for matched, _, _ in process.extract(
                    word.lower(), names, scorer=_RATIO, limit=2, score_cutoff=LINK_SCORE
                ):
                    eid = alias_map[matched]
                    if eid not in found:
                        found.append(eid)

            expansion: list[str] = []
            for eid in found:
                ent = session.get(Entity, eid)
                if ent is None:
                    continue
                terms = [ent.name_en]
                en_aliases = session.exec(
                    select(Alias.alias).where(
                        Alias.entity_id == eid, col(Alias.lang).in_(["en", "la"])
                    )
                ).all()
                # short, ASCII aliases are the ones translators actually use
                terms += sorted(
                    (a for a in en_aliases if a.isascii() and a != ent.name_en), key=len
                )[:MAX_EXPANSION_ALIASES]
                for term in terms:
                    if term not in expansion:
                        expansion.append(term)
            return found, expansion
        finally:
            self._close(session)

    def find_in_text(self, text: str, candidate_ids: Iterable[str]) -> list[str]:
        """Which of the candidate entities are named in a (Ukrainian) answer text."""
        candidates = list(dict.fromkeys(candidate_ids))
        if not candidates:
            return []
        session = self._get_session()
        try:
            names: dict[str, set[str]] = {eid: set() for eid in candidates}
            for a in session.exec(
                select(Alias).where(col(Alias.entity_id).in_(candidates), Alias.lang == "uk")
            ).all():
                names[a.entity_id].add(a.alias)
            for ent in session.exec(select(Entity).where(col(Entity.id).in_(candidates))).all():
                names[ent.id].add(ent.name_uk)
            lowered = text.lower()
            found = []
            for eid in candidates:
                for name in names.get(eid, ()):
                    stem = _stem(name)
                    if len(stem) >= 3 and re.search(rf"(?<!\w){re.escape(stem)}\w*", lowered):
                        found.append(eid)
                        break
            return found
        finally:
            self._close(session)

    def get_glossary_for_entities(self, entity_ids: Iterable[str]) -> str:
        """Name mapping for the prompt, e.g. "Achilles -> Ахілл, Hera -> Гера"."""
        ids = list(dict.fromkeys(entity_ids))
        if not ids:
            return "загальноприйнята українська традиція передачі античних імен"
        session = self._get_session()
        try:
            ents = session.exec(select(Entity).where(col(Entity.id).in_(ids))).all()
            return ", ".join(f"{e.name_en} -> {e.name_uk}" for e in ents)
        finally:
            self._close(session)
