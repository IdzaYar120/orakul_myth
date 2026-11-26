"""Entity linking for the oracle.

* Question -> entity ids (alias stem + a Ukrainian case ending: "Ахілла", "у Дельфах",
  "Немейського лева"; fuzzy only as a fallback for long words) + English names for query
  expansion.
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
FUZZY_SCORE = 85  # fallback only, for long words (transliteration variants: Ахіллес/Ахиллес)
FUZZY_MIN_LEN = 6
MAX_EXPANSION_ALIASES = 3
EXACT = 1000
# Ukrainian case endings of nouns and adjectives that may follow an alias stem
_ENDINGS = frozenset(
    (
        "а я у ю і ї и е є о ом ем єм ою ею єю ів їв ам ям ах ях ами ями ові еві єві "
        "ого ому ім им ій ий ої их іх ії ію ія ієм й"
    ).split()
) | {""}
_SOFT_END = "аяоеєиіїуюйь"
# Aliases that are ordinary words in a question ("титана" = a titan, not Helios)
_GENERIC_ALIASES = frozenset({"титан", "кора"})  # кора: "корів" (cows), not Kore


def _alias_stems(alias_word: str) -> set[str]:
    """Possible stems of one alias word: Афіна -> {афіна, афін}; Немейський -> {.., немейськ}."""
    word = alias_word.lower()
    stems = {word}
    if len(word) > 5 and word[-2:] in ("ий", "ій", "ой"):
        stems.add(word[:-2])
    if len(word) >= 3 and word[-1] in _SOFT_END:
        stems.add(word[:-1])
    return {st for st in stems if len(st) >= 2}


def word_match(word: str, alias_word: str) -> int:
    """How well a word of the text matches one alias word: EXACT, the length of the matched
    stem for an inflected form ("Дельфах" ~ "Дельфи" -> 5), or 0.

    Only a stem followed by a real case ending counts, so "Геракл" is not "Гера" and
    "сталося" is not "Талос" (the fuzzy ratio that confused them is now only a fallback).
    """
    w, a = word.lower(), alias_word.lower()
    if w == a:
        return EXACT
    best = 0
    for stem in _alias_stems(a):
        if w.startswith(stem):
            suffix = w[len(stem) :]
            # a short stem only takes a short ending: "Пан" -> "Пана", but not "Панама"
            if suffix in _ENDINGS and (len(stem) >= 4 or len(suffix) <= 2):
                best = max(best, len(stem))
    return best


def _alias_words(alias: str) -> list[str]:
    """'Ладон (дракон)' -> ['Ладон']; 'Немейський лев' -> ['Немейський', 'лев']."""
    return _WORD.findall(alias.split("(")[0])


def match_entities(text: str, aliases: Iterable[tuple[str, str]]) -> list[str]:
    """Entity ids named in `text` (pairs of alias, entity id), in order of appearance.

    For every word the best-matching aliases win: an exact alias beats an inflected one
    ("Афіна" is Athena, not Athens), a longer stem beats a shorter one ("Олімпії" is Olympia,
    not Olympus). Multi-word aliases ("Немейський лев") must match consecutive words.
    """
    tokens = _WORD.findall(text)
    single: list[tuple[str, str]] = []
    multi: list[tuple[list[str], str]] = []
    for alias, eid in aliases:
        words = _alias_words(alias)
        if not words or alias.lower() in _GENERIC_ALIASES:
            continue
        if len(words) == 1:
            single.append((words[0], eid))
        else:
            multi.append((words, eid))

    hits: list[tuple[int, str]] = []  # (word position, entity id)
    fuzzy_names = [w.lower() for w, _ in single if len(w) >= 5]
    for pos, token in enumerate(tokens):
        scores: dict[str, int] = {}
        for word, eid in single:
            score = word_match(token, word)
            if score > scores.get(eid, 0):
                scores[eid] = score
        if scores:
            top = max(scores.values())
            hits.extend((pos, eid) for eid, score in scores.items() if score == top)
        elif len(token) >= FUZZY_MIN_LEN and fuzzy_names:
            best = process.extractOne(
                token.lower(), fuzzy_names, scorer=_RATIO, score_cutoff=FUZZY_SCORE
            )
            if best:
                hits.extend((pos, eid) for w, eid in single if w.lower() == best[0])

    for words, eid in multi:
        n = len(words)
        for pos in range(len(tokens) - n + 1):
            if all(word_match(tokens[pos + k], words[k]) for k in range(n)):
                hits.append((pos, eid))
                break

    found: list[str] = []
    for _, eid in sorted(hits, key=lambda h: h[0]):
        if eid not in found:
            found.append(eid)
    return found


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
            names = [(a.alias, a.entity_id) for a in aliases]
            names += [(e.name_uk, e.id) for e in session.exec(select(Entity)).all()]
            found = match_entities(question, names)

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

    def find_in_text(self, text: str, candidate_ids: Iterable[str], lang: str = "uk") -> list[str]:
        """Which of the candidate entities are named in an answer text (Ukrainian or English)."""
        candidates = list(dict.fromkeys(candidate_ids))
        if not candidates:
            return []
        alias_langs = ["en", "la"] if lang == "en" else ["uk"]
        session = self._get_session()
        try:
            names: list[tuple[str, str]] = [
                (a.alias, a.entity_id)
                for a in session.exec(
                    select(Alias).where(
                        col(Alias.entity_id).in_(candidates), col(Alias.lang).in_(alias_langs)
                    )
                ).all()
            ]
            names += [
                (ent.name_en if lang == "en" else ent.name_uk, ent.id)
                for ent in session.exec(select(Entity).where(col(Entity.id).in_(candidates)))
            ]
            mentioned = set(match_entities(text, names))
            return [eid for eid in candidates if eid in mentioned]
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
