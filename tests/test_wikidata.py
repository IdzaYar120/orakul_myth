"""Wikidata/Pleiades import, tested offline with a fake client."""

from pathlib import Path
from typing import Any

import yaml

from delphi.ingest.wikidata import (
    WIKIDATA_SOURCE,
    Selection,
    SelectionItem,
    append_yaml,
    build_snapshot,
    draft_entries,
)


def _claim(prop_value: Any) -> dict[str, Any]:
    return {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"value": prop_value}}}


def _item(qid: str) -> dict[str, Any]:
    return {"id": qid}


ENTITIES = {
    "Q1": {  # Zeus: father Cronus, spouse Hera, child Athena + unknown child
        "labels": {"uk": {"value": "Зевс"}, "en": {"value": "Zeus"}},
        "aliases": {"en": [{"value": "Jupiter"}]},
        "descriptions": {"uk": {"value": "верховний бог"}},
        "sitelinks": {"enwiki": {}, "ukwiki": {}},
        "claims": {
            "P22": [_claim(_item("Q2"))],
            "P26": [_claim(_item("Q3"))],
            "P40": [_claim(_item("Q4")), _claim(_item("Q999"))],
        },
    },
    "Q2": {"labels": {"en": {"value": "Cronus"}}, "claims": {}},
    "Q3": {"labels": {"en": {"value": "Hera"}}, "claims": {"P26": [_claim(_item("Q1"))]}},
    "Q4": {"labels": {"en": {"value": "Athena"}}, "claims": {"P22": [_claim(_item("Q1"))]}},
    "Q10": {  # place with Pleiades id
        "labels": {"uk": {"value": "Дельфи"}, "en": {"value": "Delphi"}},
        "claims": {"P1584": [_claim("540726")], "P625": [_claim({"latitude": 1, "longitude": 2})]},
    },
    "Q11": {"labels": {"en": {"value": "Tartarus"}}, "claims": {}},
}


class FakeClient:
    def __init__(self) -> None:
        self.pleiades_calls: list[str] = []

    def get_entities(self, qids):
        return {q: ENTITIES.get(q, {"missing": ""}) for q in qids}

    def get_pleiades(self, pid: str):
        self.pleiades_calls.append(pid)
        return {"title": "Delphi", "reprPoint": [22.501169, 38.482289]}


def _selection() -> Selection:
    return Selection(
        entities=[
            SelectionItem(id="zeus", qid="Q1", type="god"),
            SelectionItem(id="cronus", qid="Q2", type="titan"),
            SelectionItem(id="hera", qid="Q3", type="god"),
            SelectionItem(id="athena", qid="Q4", type="god"),
        ],
        places=[
            SelectionItem(id="delphi", qid="Q10", type="place", place_kind="sanctuary"),
            SelectionItem(id="underworld", qid="Q11", type="place", certainty="none"),
        ],
    )


def test_snapshot_normalises_relations():
    snap = build_snapshot(FakeClient(), _selection())  # type: ignore[arg-type]
    rels = {(r["src_id"], r["rel"], r["dst_id"]) for r in snap["relations"]}
    assert rels == {
        ("cronus", "parent_of", "zeus"),  # P22 on Zeus
        ("zeus", "parent_of", "athena"),  # P40 on Zeus and P22 on Athena -> stored once
        ("hera", "spouse_of", "zeus"),  # symmetric, sorted, stored once
    }
    assert all(r["source_ref"] == WIKIDATA_SOURCE for r in snap["relations"])


def test_snapshot_place_coordinates_prefer_pleiades():
    client = FakeClient()
    snap = build_snapshot(client, _selection())  # type: ignore[arg-type]
    by_id = {e["id"]: e for e in snap["entities"]}
    assert by_id["delphi"]["coord_source"] == "pleiades"
    assert (by_id["delphi"]["lat"], by_id["delphi"]["lon"]) == (38.48229, 22.50117)
    assert by_id["underworld"].get("lat") is None  # mythical: kept off the map
    assert client.pleiades_calls == ["540726"]
    assert by_id["zeus"]["aliases_en"] == ["Jupiter"]


def test_draft_only_adds_missing_entries(tmp_path: Path):
    snap = build_snapshot(FakeClient(), _selection())  # type: ignore[arg-type]
    seed = tmp_path
    (seed / "entities.yaml").write_text(
        yaml.safe_dump([{"id": "zeus", "type": "god", "name_uk": "Зевс", "name_en": "Zeus"}]),
        encoding="utf-8",
    )
    (seed / "relations.yaml").write_text(
        yaml.safe_dump(
            [{"src_id": "zeus", "rel": "spouse_of", "dst_id": "hera", "source_ref": "Hes."}]
        ),
        encoding="utf-8",
    )

    ents, places, rels = draft_entries(snap, seed)
    assert {e["id"] for e in ents} == {"cronus", "hera", "athena"}  # zeus kept as is
    assert {p["entity_id"] for p in places} == {"delphi", "underworld"}
    assert next(p for p in places if p["entity_id"] == "underworld")["certainty"] == "none"
    # spouse relation already present in reverse direction
    assert {(r["src_id"], r["dst_id"]) for r in rels} == {("cronus", "zeus"), ("zeus", "athena")}

    append_yaml(seed / "entities.yaml", ents, "draft")
    merged = yaml.safe_load((seed / "entities.yaml").read_text(encoding="utf-8"))
    assert [e["id"] for e in merged] == ["zeus", "cronus", "hera", "athena"]


def test_selection_rejects_duplicates(tmp_path: Path):
    path = tmp_path / "selection.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "entities": [
                    {"id": "zeus", "qid": "Q1", "type": "god"},
                    {"id": "zeus2", "qid": "Q1", "type": "god"},
                ]
            }
        ),
        encoding="utf-8",
    )
    try:
        Selection.load(path)
    except ValueError as exc:
        assert "Q1" in str(exc)
    else:
        raise AssertionError("duplicate QID not detected")


def test_repo_selection_is_valid():
    from tests.paths import DATA_DIR

    sel = Selection.load(DATA_DIR / "wikidata" / "selection.yaml")
    assert len(sel.entities) >= 150 and len(sel.places) >= 60
