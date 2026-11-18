from pathlib import Path

import pytest
from sqlmodel import create_engine

from delphi.db.repo import init_db, seed_database
from delphi.encyclopedia.service import EncyclopediaService, MapService


@pytest.fixture
def seeded_engine(tmp_path: Path):
    db_file = tmp_path / "test_services.db"
    eng = create_engine(f"sqlite:///{db_file}")
    init_db(engine_override=eng)
    seed_database(engine_override=eng)
    return eng


def test_encyclopedia_service(seeded_engine):
    from sqlmodel import Session

    with Session(seeded_engine) as session:
        svc = EncyclopediaService(session=session)
        card = svc.get_entity_card("apollo")
        assert card is not None
        assert card.name_uk == "Аполлон"
        assert len(card.relations) > 0

        # Search test
        search_res = svc.search("Аполлон")
        assert len(search_res) > 0
        assert search_res[0].id == "apollo"


def test_map_service(seeded_engine):
    from sqlmodel import Session

    with Session(seeded_engine) as session:
        map_svc = MapService(session=session)
        layer = map_svc.get_map_layer()
        assert len(layer.markers) >= 2
        assert any(m.entity_id == "delphi" for m in layer.markers)
        assert len(layer.routes) >= 1
