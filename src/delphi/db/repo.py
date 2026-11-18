import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, SQLModel, create_engine, select, text

from delphi.config import settings
from delphi.db.models import (
    Alias,
    Entity,
    Myth,
    MythEntity,
    Place,
    Relation,
    Route,
)


def get_engine(db_path: Path | None = None):
    path = db_path or settings.db_path
    db_url = f"sqlite:///{path}"
    return create_engine(db_url, echo=False)


engine = get_engine()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db(engine_override=None) -> None:
    eng = engine_override or engine
    SQLModel.metadata.create_all(eng)
    _add_missing_columns(eng)

    # Initialize SQLite FTS5 virtual table for fast full-text search
    with eng.connect() as conn:
        conn.execute(
            text(
                """
            CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
                entity_id UNINDEXED,
                name_uk,
                name_en,
                aliases,
                summary_uk
            );
            """
            )
        )
        conn.commit()


def _add_missing_columns(eng) -> None:
    """Minimal migration: add columns that exist in the models but not in an older delphi.db
    (create_all never alters existing tables). Nullable columns and NOT NULL columns with a
    scalar default can be added in place; anything else needs a fresh `delphi seed` after
    deleting delphi.db, which is cheap because the DB is generated from the seed YAML."""
    with eng.connect() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table.name}")'))}
            if not existing:
                continue
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'"{column.name}" {column.type.compile(dialect=eng.dialect)}'
                if not column.nullable:
                    default = getattr(column.default, "arg", None)
                    if not isinstance(default, str | int | float | bool):
                        continue  # cannot add safely; requires recreating the DB
                    ddl += f" NOT NULL DEFAULT {_sql_literal(default)}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
        conn.commit()


def _sql_literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


SeedCounts = dict[str, int]


def _load_seed(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(yaml.safe_load(f) or [])


def seed_database(data_dir: Path | None = None, engine_override=None) -> SeedCounts:
    """Synchronise SQLite with data/seed/*.yaml (the YAML files are the source of truth).

    Idempotent: rows are inserted or updated in place, and rows that disappeared from
    the YAML are removed. Returns counts of *new* rows per table plus ``removed``.
    """
    eng = engine_override or engine
    seed_dir = (data_dir or settings.data_dir) / "seed"
    init_db(eng)

    entities_data = _load_seed(seed_dir / "entities.yaml")
    places_data = _load_seed(seed_dir / "places.yaml")
    relations_data = _load_seed(seed_dir / "relations.yaml")
    myths_data = _load_seed(seed_dir / "myths.yaml")
    routes_data = _load_seed(seed_dir / "routes.yaml")

    counts: SeedCounts = {
        "entities": 0,
        "places": 0,
        "relations": 0,
        "myths": 0,
        "routes": 0,
        "aliases": 0,
        "removed": 0,
    }

    with Session(eng) as session:
        # 1. Entities (places also get an entity row)
        entity_rows: dict[str, dict[str, Any]] = {}
        alias_rows: set[tuple[str, str, str]] = set()
        for item in entities_data:
            entity_rows[item["id"]] = {
                "type": item["type"],
                "name_uk": item["name_uk"],
                "name_en": item["name_en"],
                "name_lat": item.get("name_lat"),
                "summary_uk": item.get("summary_uk"),
                "domain": item.get("domain"),
                "symbols_json": json.dumps(item.get("symbols", []), ensure_ascii=False),
                "wikidata_id": item.get("wikidata_id"),
            }
            for a in item.get("aliases", []):
                alias_rows.add((item["id"], a["alias"], a.get("lang", "uk")))

        place_rows: dict[str, dict[str, Any]] = {}
        for item in places_data:
            eid = item["entity_id"]
            entity_rows[eid] = {
                "type": "place",
                "name_uk": item["name_uk"],
                "name_en": item["name_en"],
                "name_lat": item.get("name_lat"),
                "summary_uk": item.get("summary_uk"),
                "domain": None,
                "symbols_json": "[]",
                "wikidata_id": item.get("wikidata_id"),
            }
            for a in item.get("aliases", []):
                alias_rows.add((eid, a["alias"], a.get("lang", "uk")))
            # Mythical places (certainty: none) have no coordinates -> no map marker
            if item.get("lat") is not None and item.get("lon") is not None:
                place_rows[eid] = {
                    "lat": item["lat"],
                    "lon": item["lon"],
                    "place_kind": item["place_kind"],
                    "pleiades_id": item.get("pleiades_id"),
                    "certainty": item.get("certainty", "high"),
                }

        counts["entities"] = _sync_rows(session, Entity, entity_rows, counts)
        counts["places"] = _sync_rows(session, Place, place_rows, counts)

        # 2. Pure link tables -> set difference
        counts["aliases"] = _sync_links(
            session, Alias, ("entity_id", "alias", "lang"), alias_rows, counts
        )
        relation_rows = {
            (r["src_id"], r["rel"], r["dst_id"], r["source_ref"]) for r in relations_data
        }
        counts["relations"] = _sync_links(
            session, Relation, ("src_id", "rel", "dst_id", "source_ref"), relation_rows, counts
        )

        # 3. Myths and their participants
        myth_rows = {
            m["id"]: {
                "title_uk": m["title_uk"],
                "summary_uk": m["summary_uk"],
                "cycle": m.get("cycle", "other"),
            }
            for m in myths_data
        }
        counts["myths"] = _sync_rows(session, Myth, myth_rows, counts)
        myth_entity_rows = {
            (m["id"], e["entity_id"], e.get("role", "participant"))
            for m in myths_data
            for e in m.get("entities", [])
        }
        _sync_links(session, MythEntity, ("myth_id", "entity_id", "role"), myth_entity_rows, counts)

        # 4. Routes
        route_rows = {
            r["id"]: {
                "title_uk": r["title_uk"],
                "hero_id": r.get("hero_id"),
                "myth_id": r.get("myth_id"),
                "description_uk": r.get("description_uk"),
                "stops_json": json.dumps(r.get("stops", []), ensure_ascii=False),
            }
            for r in routes_data
        }
        counts["routes"] = _sync_rows(session, Route, route_rows, counts)

        session.commit()
        _rebuild_fts5(session)

    return counts


def _sync_rows(
    session: Session,
    model: type[SQLModel],
    rows: dict[str, dict[str, Any]],
    counts: SeedCounts,
) -> int:
    """Upsert rows keyed by primary key and delete rows that are not in ``rows``.

    Returns the number of newly created rows; deletions go to counts["removed"].
    """
    pk_col = next(iter(model.__table__.primary_key.columns))  # type: ignore[attr-defined]
    pk_name = pk_col.name
    existing = {getattr(obj, pk_name): obj for obj in session.exec(select(model)).all()}

    created = 0
    for pk, fields in rows.items():
        obj = existing.get(pk)
        if obj is None:
            session.add(model(**{pk_name: pk, **fields}))
            created += 1
            continue
        changed = False
        for key, value in fields.items():
            if getattr(obj, key) != value:
                setattr(obj, key, value)
                changed = True
        if changed:
            session.add(obj)

    for pk, obj in existing.items():
        if pk not in rows:
            session.delete(obj)
            counts["removed"] += 1
    session.flush()
    return created


def _sync_links(
    session: Session,
    model: type[SQLModel],
    fields: tuple[str, ...],
    rows: set[tuple[Any, ...]],
    counts: SeedCounts,
) -> int:
    """Make a link table contain exactly ``rows`` (tuples of ``fields`` values)."""
    existing: set[tuple[Any, ...]] = set()
    for obj in session.exec(select(model)).all():
        key = tuple(getattr(obj, f) for f in fields)
        if key in existing or key not in rows:  # duplicate or stale row
            session.delete(obj)
            counts["removed"] += 1
        else:
            existing.add(key)

    missing = rows - existing
    for key in missing:
        session.add(model(**dict(zip(fields, key, strict=True))))
    session.flush()
    return len(missing)


def _rebuild_fts5(session: Session) -> None:
    conn = session.connection()
    conn.execute(text("DELETE FROM entity_fts;"))
    aliases_by_entity: dict[str, list[str]] = {}
    for alias in session.exec(select(Alias)).all():
        aliases_by_entity.setdefault(alias.entity_id, []).append(alias.alias)
    for ent in session.exec(select(Entity)).all():
        conn.execute(
            text(
                """
            INSERT INTO entity_fts (entity_id, name_uk, name_en, aliases, summary_uk)
            VALUES (:entity_id, :name_uk, :name_en, :aliases, :summary_uk);
            """
            ),
            parameters={
                "entity_id": ent.id,
                "name_uk": ent.name_uk,
                "name_en": ent.name_en,
                "aliases": " ".join(aliases_by_entity.get(ent.id, [])),
                "summary_uk": ent.summary_uk or "",
            },
        )
    session.commit()
