import json
from collections.abc import Generator
from pathlib import Path

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


def seed_database(data_dir: Path | None = None, engine_override=None) -> dict[str, int]:
    eng = engine_override or engine
    base_dir = data_dir or settings.data_dir
    seed_dir = base_dir / "seed"

    init_db(eng)
    counts = {"entities": 0, "places": 0, "relations": 0, "myths": 0, "routes": 0, "aliases": 0}

    with Session(eng) as session:
        # 1. Entities
        entities_file = seed_dir / "entities.yaml"
        if entities_file.exists():
            with open(entities_file, encoding="utf-8") as f:
                entities_data = yaml.safe_load(f) or []
            for item in entities_data:
                existing = session.get(Entity, item["id"])
                symbols = item.get("symbols", [])
                symbols_json = json.dumps(symbols, ensure_ascii=False)

                if not existing:
                    entity = Entity(
                        id=item["id"],
                        type=item["type"],
                        name_uk=item["name_uk"],
                        name_en=item["name_en"],
                        name_lat=item.get("name_lat"),
                        summary_uk=item.get("summary_uk"),
                        domain=item.get("domain"),
                        symbols_json=symbols_json,
                        wikidata_id=item.get("wikidata_id"),
                    )
                    session.add(entity)
                    counts["entities"] += 1

                # Aliases from entity
                aliases = item.get("aliases", [])
                for a in aliases:
                    # check if alias already exists
                    stmt = select(Alias).where(
                        Alias.entity_id == item["id"],
                        Alias.alias == a["alias"],
                        Alias.lang == a.get("lang", "uk"),
                    )
                    if not session.exec(stmt).first():
                        alias_obj = Alias(
                            entity_id=item["id"],
                            alias=a["alias"],
                            lang=a.get("lang", "uk"),
                        )
                        session.add(alias_obj)
                        counts["aliases"] += 1

        # 2. Places
        places_file = seed_dir / "places.yaml"
        if places_file.exists():
            with open(places_file, encoding="utf-8") as f:
                places_data = yaml.safe_load(f) or []
            for item in places_data:
                # also ensure entity exists for the place
                existing_entity = session.get(Entity, item["entity_id"])
                if not existing_entity:
                    entity = Entity(
                        id=item["entity_id"],
                        type="place",
                        name_uk=item["name_uk"],
                        name_en=item["name_en"],
                        name_lat=item.get("name_lat"),
                        summary_uk=item.get("summary_uk"),
                    )
                    session.add(entity)
                    counts["entities"] += 1

                existing_place = session.get(Place, item["entity_id"])
                if not existing_place:
                    place = Place(
                        entity_id=item["entity_id"],
                        lat=item["lat"],
                        lon=item["lon"],
                        place_kind=item["place_kind"],
                        pleiades_id=item.get("pleiades_id"),
                        certainty=item.get("certainty", "high"),
                    )
                    session.add(place)
                    counts["places"] += 1

                aliases = item.get("aliases", [])
                for a in aliases:
                    stmt = select(Alias).where(
                        Alias.entity_id == item["entity_id"],
                        Alias.alias == a["alias"],
                    )
                    if not session.exec(stmt).first():
                        session.add(
                            Alias(
                                entity_id=item["entity_id"],
                                alias=a["alias"],
                                lang=a.get("lang", "uk"),
                            )
                        )
                        counts["aliases"] += 1

        # 3. Relations
        relations_file = seed_dir / "relations.yaml"
        if relations_file.exists():
            with open(relations_file, encoding="utf-8") as f:
                relations_data = yaml.safe_load(f) or []
            for item in relations_data:
                rel_stmt = select(Relation).where(
                    Relation.src_id == item["src_id"],
                    Relation.rel == item["rel"],
                    Relation.dst_id == item["dst_id"],
                    Relation.source_ref == item["source_ref"],
                )
                if not session.exec(rel_stmt).first():
                    relation = Relation(
                        src_id=item["src_id"],
                        rel=item["rel"],
                        dst_id=item["dst_id"],
                        source_ref=item["source_ref"],
                    )
                    session.add(relation)
                    counts["relations"] += 1

        # 4. Myths
        myths_file = seed_dir / "myths.yaml"
        if myths_file.exists():
            with open(myths_file, encoding="utf-8") as f:
                myths_data = yaml.safe_load(f) or []
            for item in myths_data:
                existing_myth = session.get(Myth, item["id"])
                if not existing_myth:
                    myth = Myth(
                        id=item["id"],
                        title_uk=item["title_uk"],
                        summary_uk=item["summary_uk"],
                        cycle=item.get("cycle", "general"),
                    )
                    session.add(myth)
                    counts["myths"] += 1

                for ent in item.get("entities", []):
                    myth_stmt = select(MythEntity).where(
                        MythEntity.myth_id == item["id"],
                        MythEntity.entity_id == ent["entity_id"],
                    )
                    if not session.exec(myth_stmt).first():
                        session.add(
                            MythEntity(
                                myth_id=item["id"],
                                entity_id=ent["entity_id"],
                                role=ent.get("role", "participant"),
                            )
                        )

        # 5. Routes
        routes_file = seed_dir / "routes.yaml"
        if routes_file.exists():
            with open(routes_file, encoding="utf-8") as f:
                routes_data = yaml.safe_load(f) or []
            for item in routes_data:
                existing_route = session.get(Route, item["id"])
                stops_json = json.dumps(item.get("stops", []), ensure_ascii=False)
                if not existing_route:
                    route = Route(
                        id=item["id"],
                        title_uk=item["title_uk"],
                        hero_id=item.get("hero_id"),
                        description_uk=item.get("description_uk"),
                        stops_json=stops_json,
                    )
                    session.add(route)
                    counts["routes"] += 1

        session.commit()

        # Refresh FTS5 index
        _rebuild_fts5(session)

    return counts


def _rebuild_fts5(session: Session) -> None:
    conn = session.connection()
    conn.execute(text("DELETE FROM entity_fts;"))
    entities = session.exec(select(Entity)).all()
    for ent in entities:
        aliases_list = session.exec(select(Alias.alias).where(Alias.entity_id == ent.id)).all()
        aliases_str = " ".join(aliases_list)
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
                "aliases": aliases_str,
                "summary_uk": ent.summary_uk or "",
            },
        )
    session.commit()
