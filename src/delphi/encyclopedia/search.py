import re
from collections.abc import Callable

from rapidfuzz import fuzz, process, utils
from sqlmodel import Session, select, text

from delphi.db.models import Alias
from delphi.db.repo import engine

# rapidfuzz stubs declare scorers as overloads that some type checkers (Pyrefly)
# can't match to process.extract's `scorer` protocol; the explicit Callable type
# fixes that while keeping the native C implementation.
_WRATIO: Callable[..., float] = fuzz.WRatio

STRONG_NAME_SCORE = 88  # "Персефону" ~ "Персефона", "Зевсс" ~ "Зевс"
WEAK_NAME_SCORE = 65  # fallback when nothing else matched

# Column weights for bm25(): entity_id, name_uk, name_en, aliases, summary_uk.
# Names and aliases outrank mentions in someone else's summary.
_FTS_SQL = text(
    "SELECT entity_id FROM entity_fts WHERE entity_fts MATCH :q "
    "ORDER BY bm25(entity_fts, 0.0, 10.0, 10.0, 5.0, 1.0) LIMIT :limit;"
)


def _stem(token: str) -> str:
    """Crude stemming for prefix search: drop a Ukrainian case ending.

    "Персефону" -> "Персефо", "Ахілла" -> "Ахілл", "Зевса" -> "Зевс".
    """
    if len(token) >= 8:
        return token[:-2]
    if len(token) >= 5:
        return token[:-1]
    return token


def fts_query(query: str) -> str | None:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return None
    return " ".join(f'"{_stem(t)}"*' for t in tokens)


def _fuzzy(query: str, aliases: dict[str, str], cutoff: int, limit: int) -> list[str]:
    matches = process.extract(
        query,
        list(aliases),
        scorer=_WRATIO,
        processor=utils.default_process,
        limit=limit,
        score_cutoff=cutoff,
    )
    return list(dict.fromkeys(aliases[m[0]] for m in matches))


def search_entities(query: str, session: Session | None = None, limit: int = 20) -> list[str]:
    """Search entities by name, alias (uk/en/la) or summary text.

    Order: strong fuzzy name matches (tolerates case endings and typos), then SQLite
    FTS5 prefix matches ranked by BM25, then weak fuzzy matches as a last resort.
    Returns entity ids.
    """
    query = query.strip()
    if not query:
        return []

    sess = session or Session(engine)
    try:
        aliases = {a.alias: a.entity_id for a in sess.exec(select(Alias)).all()}
        ids = _fuzzy(query, aliases, STRONG_NAME_SCORE, limit) if aliases else []

        q = fts_query(query)
        if q:
            rows = sess.connection().execute(_FTS_SQL, {"q": q, "limit": limit}).fetchall()
            ids += [str(r[0]) for r in rows]

        if not ids and aliases:
            ids = _fuzzy(query, aliases, WEAK_NAME_SCORE, limit)

        return list(dict.fromkeys(ids))[:limit]
    finally:
        if session is None:
            sess.close()
