"""Validation of hand-edited seed YAML: ids, references, coordinates, vocabularies."""

from typing import Any

import pytest
import yaml

from delphi.encyclopedia.vocab import (
    CERTAINTY,
    ENTITY_TYPES,
    MYTH_CYCLES,
    MYTH_ROLES,
    PLACE_KINDS,
    RELATION_TYPES,
)
from tests.paths import DATA_DIR

SEED = DATA_DIR / "seed"
ALIAS_LANGS = {"uk", "en", "la", "el"}

# Mediterranean + Black Sea + Caucasus bounding box
LAT_RANGE = (25.0, 48.0)
LON_RANGE = (-10.0, 50.0)


def _load(name: str) -> Any:
    with open(SEED / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


@pytest.fixture(scope="module")
def entities() -> list[dict[str, Any]]:
    return list(_load("entities.yaml"))


@pytest.fixture(scope="module")
def places() -> list[dict[str, Any]]:
    return list(_load("places.yaml"))


@pytest.fixture(scope="module")
def all_ids(entities, places) -> set[str]:
    return {e["id"] for e in entities} | {p["entity_id"] for p in places}


def test_mvp_size(entities, places):
    """Architecture doc, Stage 1: ~150 entities and ~60 places."""
    assert len(entities) >= 150
    assert len(places) >= 60


def test_ids_are_unique(entities, places):
    ids = [e["id"] for e in entities] + [p["entity_id"] for p in places]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"Duplicate ids: {duplicates}"


def test_entities_have_required_fields(entities):
    for e in entities:
        for field in ("id", "type", "name_uk", "name_en", "summary_uk"):
            assert e.get(field), f"{e.get('id')}: missing {field}"
        assert e["type"] in ENTITY_TYPES and e["type"] != "place", f"{e['id']}: type {e['type']}"
        assert isinstance(e.get("symbols", []), list)


def test_aliases_valid(entities, places):
    for item in entities + places:
        eid = item.get("id") or item.get("entity_id")
        assert item.get("aliases"), f"{eid}: no aliases"
        for a in item["aliases"]:
            assert a.get("alias"), item
            assert a.get("lang", "uk") in ALIAS_LANGS, a


def test_alias_does_not_point_to_two_entities(entities, places):
    owners: dict[str, set[str]] = {}
    for item in entities + places:
        eid = item.get("id") or item.get("entity_id")
        for a in item["aliases"]:
            owners.setdefault(a["alias"].lower(), set()).add(eid)
    ambiguous = {a: o for a, o in owners.items() if len(o) > 1}
    assert not ambiguous, f"Aliases shared by several entities: {ambiguous}"


def test_places_coordinates_and_kinds(places):
    for p in places:
        eid = p["entity_id"]
        assert p["place_kind"] in PLACE_KINDS, eid
        certainty = p.get("certainty", "high")
        assert certainty in CERTAINTY, eid
        if certainty == "none":
            assert "lat" not in p and "lon" not in p, f"{eid}: mythical place with coordinates"
            continue
        assert LAT_RANGE[0] <= p["lat"] <= LAT_RANGE[1], f"{eid}: lat {p['lat']}"
        assert LON_RANGE[0] <= p["lon"] <= LON_RANGE[1], f"{eid}: lon {p['lon']}"


def test_relations_reference_existing_ids(all_ids):
    seen = set()
    for r in _load("relations.yaml"):
        assert r["src_id"] in all_ids, f"Unknown src_id: {r}"
        assert r["dst_id"] in all_ids, f"Unknown dst_id: {r}"
        assert r["src_id"] != r["dst_id"], r
        assert r["rel"] in RELATION_TYPES, f"Unknown rel: {r}"
        assert r.get("source_ref"), f"source_ref is required: {r}"
        key = (r["src_id"], r["rel"], r["dst_id"], r["source_ref"])
        assert key not in seen, f"Duplicate relation: {r}"
        seen.add(key)


def test_place_relations_point_to_places(places):
    place_ids = {p["entity_id"] for p in places}
    for r in _load("relations.yaml"):
        if r["rel"] in {"worshipped_at", "born_at", "ruled"}:
            assert r["dst_id"] in place_ids, f"{r['rel']} must point to a place: {r}"


def test_no_parent_cycles():
    parents: dict[str, set[str]] = {}
    for r in _load("relations.yaml"):
        if r["rel"] == "parent_of":
            parents.setdefault(r["dst_id"], set()).add(r["src_id"])

    def ancestors(eid: str, path: tuple[str, ...]) -> None:
        for p in parents.get(eid, ()):
            assert p not in path, f"Parent cycle: {' -> '.join((*path, p))}"
            ancestors(p, (*path, p))

    for eid in parents:
        ancestors(eid, (eid,))


def test_myths_valid(all_ids):
    myths = _load("myths.yaml")
    assert len({m["id"] for m in myths}) == len(myths)
    for m in myths:
        assert m.get("title_uk") and m.get("summary_uk"), m["id"]
        assert m["cycle"] in MYTH_CYCLES, f"{m['id']}: cycle {m['cycle']}"
        assert m.get("entities"), f"{m['id']}: no participants"
        for ent in m["entities"]:
            assert ent["entity_id"] in all_ids, f"{m['id']}: unknown {ent['entity_id']}"
            assert ent.get("role", "participant") in MYTH_ROLES, f"{m['id']}: {ent}"


def test_routes_reference_existing_ids(all_ids):
    for r in _load("routes.yaml"):
        if r.get("hero_id"):
            assert r["hero_id"] in all_ids, r["id"]
        stops = r.get("stops", [])
        assert len(stops) >= 2, f"{r['id']}: route needs at least 2 stops"
        numbers = [s["stop_number"] for s in stops]
        assert numbers == sorted(numbers), f"{r['id']}: stops out of order"
        for s in stops:
            assert s["entity_id"] in all_ids, f"{r['id']}: unknown stop {s['entity_id']}"
            assert LAT_RANGE[0] <= s["lat"] <= LAT_RANGE[1]
            assert LON_RANGE[0] <= s["lon"] <= LON_RANGE[1]
            assert s.get("source_ref"), f"{r['id']}: stop without source_ref"


def test_seed_matches_wikidata_selection(entities, places):
    """Every selected Wikidata item is in the seed with the same QID (and vice versa)."""
    with open(DATA_DIR / "wikidata" / "selection.yaml", encoding="utf-8") as f:
        sel = yaml.safe_load(f)
    selected = {i["id"]: i["qid"] for i in sel["entities"] + sel["places"]}
    seeded = {e["id"]: e.get("wikidata_id") for e in entities}
    seeded |= {p["entity_id"]: p.get("wikidata_id") for p in places}
    assert selected == seeded


def test_sources_have_license():
    with open(DATA_DIR / "sources.yaml", encoding="utf-8") as f:
        sources = (yaml.safe_load(f) or {}).get("sources", [])
    assert sources
    for s in sources:
        for field in ("id", "author", "title", "translator", "license", "url", "format"):
            assert s.get(field), f"{s.get('id')}: missing {field}"
