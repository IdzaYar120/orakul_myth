from rapidfuzz import fuzz, process
from sqlmodel import Session, select, text

from delphi.db.models import Alias
from delphi.db.repo import engine


def search_entities(query: str, session: Session | None = None) -> list[str]:
    """Search entities: SQLite FTS5 first, then rapidfuzz on aliases as fallback.

    Returns a list of matching entity_ids.
    """
    query = query.strip()
    if not query:
        return []

    sess = session or Session(engine)
    try:
        # 1. Try SQLite FTS5
        # Escape quotes for FTS5 syntax
        clean_q = query.replace('"', '""')
        # Enable prefix search
        fts_query = f'"{clean_q}"*'
        stmt = text("SELECT entity_id FROM entity_fts WHERE entity_fts MATCH :q LIMIT 20;")
        results = sess.connection().execute(stmt, parameters={"q": fts_query}).fetchall()
        ids = [str(r[0]) for r in results]
        if ids:
            return ids

        # 2. Fallback: RapidFuzz across all known aliases
        all_aliases = sess.exec(select(Alias)).all()
        if not all_aliases:
            return []

        alias_map = {a.alias: a.entity_id for a in all_aliases}
        matches = process.extract(
            query,
            list(alias_map.keys()),
            scorer=fuzz.WRatio,
            limit=10,
            score_cutoff=65,
        )

        matched_ids: list[str] = []
        for match_str, score, _ in matches:
            ent_id = alias_map[match_str]
            if ent_id not in matched_ids:
                matched_ids.append(ent_id)

        return matched_ids
    finally:
        if session is None:
            sess.close()
