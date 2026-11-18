from sqlmodel import Session

from delphi.encyclopedia.service import EncyclopediaService, MapService


def _ids(items) -> list[str]:
    return [i.entity.id for i in items]


def test_search_and_filters(seeded_session: Session):
    svc = EncyclopediaService(session=seeded_session)
    res = svc.search("Аполлон")
    assert res and res[0].id == "apollo"

    assert all(r.type == "place" for r in svc.search("Аполлон", entity_type="place"))
    assert "delphi" in [r.id for r in svc.search("Аполлон", entity_type="place")]

    trojan = {r.id for r in svc.list_entities(cycle="trojan")}
    assert {"achilles", "hector", "troy"} <= trojan
    assert "cronus" not in trojan

    gods = svc.list_entities(entity_type="god")
    assert gods and all(e.type == "god" for e in gods)
    assert [g.name_uk for g in gods] == sorted((g.name_uk for g in gods), key=str.lower)


def test_card_lineage(seeded_session: Session):
    svc = EncyclopediaService(session=seeded_session)
    zeus = svc.get_entity_card("zeus")
    assert zeus is not None
    assert set(_ids(zeus.lineage.parents)) == {"cronus", "rhea"}
    assert "hera" in _ids(zeus.lineage.spouses)
    assert {"athena", "apollo", "heracles"} <= set(_ids(zeus.lineage.children))
    # Full siblings share both parents
    assert {"hera", "poseidon", "hades", "demeter", "hestia"} <= set(_ids(zeus.lineage.siblings))

    children = {c.entity.id: c for c in zeus.lineage.children}
    assert children["athena"].source_refs == ["Hes. Theog. 924"]
    assert children["athena"].verified


def test_card_keeps_myth_variants_apart(seeded_session: Session):
    """Aphrodite: Hesiod (Uranus) vs Homer (Zeus and Dione) — both versions with sources."""
    card = EncyclopediaService(session=seeded_session).get_entity_card("aphrodite")
    assert card is not None
    parents = {p.entity.id: p.source_refs for p in card.lineage.parents}
    assert parents["uranus"] == ["Hes. Theog. 188"]
    assert parents["zeus"] == ["Hom. Il. 5.370"]
    assert "dione" in parents
    # Children of different "parents" are half-siblings, grouped by the shared parent
    assert card.lineage.siblings == []
    vias = {g.via.id for g in card.lineage.half_siblings}
    assert {"zeus", "uranus"} <= vias


def test_card_relations_and_places(seeded_session: Session):
    svc = EncyclopediaService(session=seeded_session)
    apollo = svc.get_entity_card("apollo")
    assert apollo is not None
    groups = {(g.rel, g.direction): g for g in apollo.other_relations}
    assert "delphi" in _ids(groups[("worshipped_at", "out")].items)
    assert "python" in _ids(groups[("killed", "out")].items)
    assert {"delphi", "delos"} <= {p.entity_id for p in apollo.places}
    assert apollo.place is None

    delphi = svc.get_entity_card("delphi")
    assert delphi is not None
    assert delphi.place is not None and delphi.place.pleiades_id == 540726
    worshipped = {(g.rel, g.direction): g for g in delphi.other_relations}
    assert "apollo" in _ids(worshipped[("worshipped_at", "in")].items)
    assert delphi.places[0].entity_id == "delphi"


def test_card_myths_and_unverified_relations(seeded_session: Session):
    svc = EncyclopediaService(session=seeded_session)
    odysseus = svc.get_entity_card("odysseus")
    assert odysseus is not None
    assert "trojan" in odysseus.cycles
    homecoming = next(m for m in odysseus.myths if m.id == "odysseus_homecoming")
    assert homecoming.role == "protagonist"
    assert "penelope" in [p.id for p in homecoming.participants]

    telemachus = next(c for c in odysseus.lineage.children if c.entity.id == "telemachus")
    assert telemachus.source_refs == ["Wikidata"]
    assert not telemachus.verified

    assert svc.get_entity_card("no_such_entity") is None
    assert odysseus.passages == []  # filled by `delphi ingest` in Stage 3


def test_mythical_place_card(seeded_session: Session):
    card = EncyclopediaService(session=seeded_session).get_entity_card("underworld")
    assert card is not None
    assert card.type == "place" and card.place is None and card.places == []
    assert "hades" in _ids(next(g for g in card.other_relations if g.rel == "ruled").items)


def test_map_service(seeded_session: Session):
    map_svc = MapService(session=seeded_session)
    layer = map_svc.get_map_layer()
    assert len(layer.markers) >= 60
    delphi = next(m for m in layer.markers if m.entity_id == "delphi")
    assert [p.id for p in delphi.patrons] == ["apollo"]
    assert not any(m.entity_id == "underworld" for m in layer.markers)
    assert "underworld" in {r.id for r in layer.off_map}
    assert {r.id for r in layer.routes} == {"odysseus_wanderings", "argonauts_voyage"}

    sanctuaries = map_svc.get_map_layer(place_kind="sanctuary")
    assert sanctuaries.markers and all(m.place_kind == "sanctuary" for m in sanctuaries.markers)
    two_kinds = map_svc.get_map_layer(place_kinds=["island", "mountain"])
    assert {m.place_kind for m in two_kinds.markers} == {"island", "mountain"}


def test_map_filters_by_god_and_myth(seeded_session: Session):
    map_svc = MapService(session=seeded_session)
    zeus = {m.entity_id for m in map_svc.get_map_layer(god_id="zeus").markers}
    assert {"olympia", "dodona"} <= zeus and "delphi" not in zeus

    fleece = map_svc.get_map_layer(myth_id="golden_fleece")
    assert {"iolcus", "colchis", "lemnos"} <= {m.entity_id for m in fleece.markers}
    assert [r.id for r in fleece.routes] == ["argonauts_voyage"]

    assert map_svc.get_map_layer(route_ids=[]).routes == []


def test_map_routes_and_options(seeded_session: Session):
    map_svc = MapService(session=seeded_session)
    odyssey = map_svc.get_map_layer(route_ids=["odysseus_wanderings"]).routes[0]
    assert odyssey.stops[0].entity_id == "troy" and odyssey.stops[-1].entity_id == "ithaca"
    assert odyssey.is_speculative
    assert any(s.entity_id is None for s in odyssey.stops)  # Lotus-eaters etc.

    options = map_svc.filter_options()
    assert "zeus" in {g.id for g in options.gods}
    assert "golden_fleece" in {m.id for m in options.myths}
    assert [k.id for k in options.place_kinds][0] == "sanctuary"


def test_nearest_place(seeded_session: Session):
    map_svc = MapService(session=seeded_session)
    assert map_svc.nearest_place(38.49, 22.50) == "delphi"
    assert map_svc.nearest_place(0.0, 0.0) is None  # nothing within 30 km
