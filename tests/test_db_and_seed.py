from pathlib import Path

import pytest
from sqlmodel import Session, create_engine

from delphi.db.models import Entity, Place
from delphi.db.repo import init_db, seed_database
from delphi.encyclopedia.search import search_entities


@pytest.fixture
def in_memory_engine(tmp_path: Path):
    db_file = tmp_path / "test_delphi.db"
    eng = create_engine(f"sqlite:///{db_file}")
    init_db(engine_override=eng)
    return eng


def test_seed_and_search(in_memory_engine):
    counts = seed_database(engine_override=in_memory_engine)
    assert counts["entities"] > 0
    assert counts["places"] > 0
    assert counts["relations"] > 0

    with Session(in_memory_engine) as session:
        zeus = session.get(Entity, "zeus")
        assert zeus is not None
        assert zeus.name_uk == "Зевс"
        assert "блискавка" in zeus.symbols

        delphi_place = session.get(Place, "delphi")
        assert delphi_place is not None
        assert delphi_place.place_kind == "sanctuary"

        # FTS5 search test
        found = search_entities("Зевс", session=session)
        assert "zeus" in found

        # RapidFuzz fuzzy search test (typo tolerance)
        found_typo = search_entities("Зевсс", session=session)
        assert "zeus" in found_typo
