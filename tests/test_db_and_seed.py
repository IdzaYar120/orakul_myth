from pathlib import Path

import yaml
from sqlalchemy import Engine
from sqlmodel import Session, select

from delphi.db.models import Alias, Entity, Place, Relation
from delphi.db.repo import seed_database
from delphi.encyclopedia.search import fts_query, search_entities
from tests.paths import DATA_DIR


def test_seed_and_search(seeded_session: Session):
    zeus = seeded_session.get(Entity, "zeus")
    assert zeus is not None
    assert zeus.name_uk == "Зевс"
    assert "блискавка" in zeus.symbols

    delphi_place = seeded_session.get(Place, "delphi")
    assert delphi_place is not None
    assert delphi_place.place_kind == "sanctuary"
    assert delphi_place.pleiades_id == 540726

    # FTS5 search
    assert search_entities("Зевс", session=seeded_session)[0] == "zeus"
    # English and Latin names / aliases
    assert "zeus" in search_entities("Jupiter", session=seeded_session)
    assert search_entities("Ulysses", session=seeded_session)[0] == "odysseus"
    # Typos (fuzzy)
    assert search_entities("Зевсс", session=seeded_session)[0] == "zeus"
    assert search_entities("   ", session=seeded_session) == []


def test_search_handles_ukrainian_case_endings(seeded_session: Session):
    # "Персефону" (accusative) must find Persephone, not just entities mentioning her
    assert search_entities("Персефону", session=seeded_session)[0] == "persephone"
    assert search_entities("Ахілла", session=seeded_session)[0] == "achilles"
    assert search_entities("Діоніса", session=seeded_session)[0] == "dionysus"


def test_fts_query_stems_tokens():
    assert fts_query("Персефону") == '"Персефо"*'
    assert fts_query("Зевс") == '"Зевс"*'
    assert fts_query('сад "Гесперид"') == '"сад"* "Геспер"*'
    assert fts_query("  ") is None


def test_search_ranks_name_above_summary_mention(seeded_session: Session):
    # Delphi's summary mentions Apollo, but the name match must come first.
    found = search_entities("Аполлон", session=seeded_session)
    assert found[0] == "apollo"
    assert "delphi" in found


def test_mythical_place_has_no_map_marker(seeded_session: Session):
    underworld = seeded_session.get(Entity, "underworld")
    assert underworld is not None and underworld.type == "place"
    assert seeded_session.get(Place, "underworld") is None


def test_seed_is_idempotent(seeded_engine: Engine):
    counts = seed_database(data_dir=DATA_DIR, engine_override=seeded_engine)
    assert all(v == 0 for v in counts.values()), counts

    with Session(seeded_engine) as session:
        zeus_aliases = session.exec(select(Alias).where(Alias.entity_id == "zeus")).all()
        assert len(zeus_aliases) == len({(a.alias, a.lang) for a in zeus_aliases})


def _write_seed(tmp_path: Path, entities: list[dict], relations: list[dict]) -> Path:
    seed_dir = tmp_path / "data" / "seed"
    seed_dir.mkdir(parents=True)
    (seed_dir / "entities.yaml").write_text(
        yaml.safe_dump(entities, allow_unicode=True), encoding="utf-8"
    )
    (seed_dir / "relations.yaml").write_text(
        yaml.safe_dump(relations, allow_unicode=True), encoding="utf-8"
    )
    return tmp_path / "data"


def test_seed_syncs_with_yaml(tmp_path: Path, seeded_engine: Engine):
    """Edits in the YAML are applied, and rows removed from the YAML disappear from the DB."""
    entities = [
        {
            "id": "zeus",
            "type": "god",
            "name_uk": "Зевс",
            "name_en": "Zeus",
            "summary_uk": "Оновлений опис.",
            "symbols": ["орел"],
            "aliases": [{"alias": "Зевс", "lang": "uk"}],
        },
        {"id": "hera", "type": "god", "name_uk": "Гера", "name_en": "Hera"},
    ]
    relations = [
        {"src_id": "hera", "rel": "spouse_of", "dst_id": "zeus", "source_ref": "Hes. Theog. 921"}
    ]
    data_dir = _write_seed(tmp_path, entities, relations)

    counts = seed_database(data_dir=data_dir, engine_override=seeded_engine)
    assert counts["entities"] == 0  # both already existed
    assert counts["removed"] > 0

    with Session(seeded_engine) as session:
        zeus = session.get(Entity, "zeus")
        assert zeus is not None
        assert zeus.summary_uk == "Оновлений опис."
        assert zeus.symbols == ["орел"]
        assert session.get(Entity, "apollo") is None  # removed from YAML
        assert session.get(Place, "delphi") is None  # places.yaml missing -> no places
        assert len(session.exec(select(Relation)).all()) == 1
        assert [a.alias for a in session.exec(select(Alias)).all()] == ["Зевс"]
        # FTS index is rebuilt from the updated rows
        assert search_entities("Оновлений", session=session) == ["zeus"]


def test_init_db_adds_missing_columns(tmp_path: Path):
    """An older delphi.db without route.myth_id is upgraded in place."""
    from sqlalchemy import create_engine, text

    from delphi.db.repo import init_db

    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE route (id VARCHAR PRIMARY KEY, title_uk VARCHAR)"))
        conn.commit()
    init_db(engine_override=eng)
    with eng.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(route)"))}
    assert {"myth_id", "hero_id", "stops_json"} <= cols
