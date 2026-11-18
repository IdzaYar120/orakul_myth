"""Wikidata + Pleiades import for the encyclopedia seed (Stage 1).

Workflow (the seed YAML stays the hand-edited source of truth, Wikidata only proposes):

1. ``delphi wikidata candidates`` — SPARQL: ranked list of mythological figures
   (by number of Wikipedia sitelinks) to help choose what goes into the selection.
2. ``data/wikidata/selection.yaml`` — hand-curated list: our id + QID + type
   (and place_kind for places).
3. ``delphi wikidata pull`` — fetch labels, aliases, descriptions, family
   relations (P22/P25/P26/P40) and Pleiades ids/coordinates into
   ``data/wikidata/snapshot.yaml``.
4. ``delphi wikidata draft`` — append entries that are *not yet* in
   ``data/seed/*.yaml``; existing (hand-edited) entries are never touched.

Wikidata is CC0; Pleiades is CC BY (attribution shown on the map).
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from delphi.config import settings

USER_AGENT = (
    "DelphiOracleBot/0.1 (https://github.com/IdzaYar120/orakul_myth; educational RAG project) "
    f"httpx/{httpx.__version__}"
)
SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
PLEIADES_URL = "https://pleiades.stoa.org/places/{pid}/json"

# Wikidata classes used to find candidates -> suggested entity type
CANDIDATE_CLASSES: dict[str, str] = {
    "Q113103481": "god",  # Olympian god
    "Q22989102": "god",  # Greek deity
    "Q878099": "god",  # Greek primordial deity
    "Q45713": "titan",  # titan
    "Q23015925": "hero",  # demigod of Greek mythology
    "Q12502038": "hero",  # Greek heroes
    "Q22988604": "mortal",  # mythological Greek character
}

# Family properties
P_FATHER, P_MOTHER, P_SPOUSE, P_CHILD = "P22", "P25", "P26", "P40"
P_PLEIADES, P_COORD = "P1584", "P625"

WIKIDATA_SOURCE = "Wikidata"
"""source_ref prefix for relations not yet checked against an ancient text."""


def default_dir() -> Path:
    return settings.data_dir / "wikidata"


# --------------------------------------------------------------------------- HTTP


class WikidataClient:
    """Small polite client: descriptive User-Agent, retries with Retry-After on 429/5xx."""

    def __init__(self, client: httpx.Client | None = None, max_retries: int = 5):
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True
        )
        self.max_retries = max_retries

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self.max_retries):
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(5.0 * 2**attempt)
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 5.0 * 2**attempt
                time.sleep(min(delay, 120.0))
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def sparql(self, query: str) -> list[dict[str, Any]]:
        resp = self._request(
            "POST",
            SPARQL_URL,
            data={"query": query},
            headers={"Accept": "application/sparql-results+json"},
        )
        return list(resp.json()["results"]["bindings"])

    def get_entities(self, qids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """wbgetentities in batches of 50 (API limit)."""
        out: dict[str, dict[str, Any]] = {}
        for batch in _chunks(list(dict.fromkeys(qids)), 50):
            resp = self._request(
                "GET",
                API_URL,
                params={
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|aliases|descriptions|claims|sitelinks",
                    "languages": "uk|en|la",
                    "format": "json",
                },
            )
            out.update(resp.json().get("entities", {}))
        return out

    def get_pleiades(self, pid: str) -> dict[str, Any] | None:
        try:
            resp = self._request("GET", PLEIADES_URL.format(pid=pid))
        except httpx.HTTPStatusError:
            return None
        data: dict[str, Any] = resp.json()
        return data


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# --------------------------------------------------------------------------- candidates


def fetch_candidates(client: WikidataClient, min_sitelinks: int = 25) -> list[dict[str, Any]]:
    """Mythological figures ranked by Wikipedia sitelinks (a proxy for prominence)."""
    classes = " ".join(f"wd:{c}" for c in CANDIDATE_CLASSES)
    query = f"""
    SELECT ?item ?cls ?en ?uk ?sl WHERE {{
      VALUES ?cls {{ {classes} }}
      ?item wdt:P31 ?cls ; wikibase:sitelinks ?sl .
      FILTER(?sl >= {min_sitelinks:d})
      OPTIONAL {{ ?item rdfs:label ?en FILTER(lang(?en) = "en") }}
      OPTIONAL {{ ?item rdfs:label ?uk FILTER(lang(?uk) = "uk") }}
    }}"""
    found: dict[str, dict[str, Any]] = {}
    for row in client.sparql(query):
        qid = _qid(row["item"]["value"])
        cand = found.setdefault(
            qid,
            {
                "qid": qid,
                "name_en": row.get("en", {}).get("value"),
                "name_uk": row.get("uk", {}).get("value"),
                "sitelinks": int(row["sl"]["value"]),
                "types": [],
            },
        )
        typ = CANDIDATE_CLASSES[_qid(row["cls"]["value"])]
        if typ not in cand["types"]:
            cand["types"].append(typ)
    return sorted(found.values(), key=lambda c: -int(c["sitelinks"]))


# --------------------------------------------------------------------------- snapshot


@dataclass
class SelectionItem:
    id: str
    qid: str
    type: str
    place_kind: str | None = None
    pleiades_id: str | None = None  # manual override
    certainty: str | None = None


@dataclass
class Selection:
    entities: list[SelectionItem] = field(default_factory=list)
    places: list[SelectionItem] = field(default_factory=list)

    @property
    def all(self) -> list[SelectionItem]:
        return self.entities + self.places

    @classmethod
    def load(cls, path: Path) -> Selection:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        ents = [SelectionItem(**_str_values(e)) for e in raw.get("entities", [])]
        places = [SelectionItem(type="place", **_str_values(p)) for p in raw.get("places", [])]
        sel = cls(entities=ents, places=places)
        sel.validate()
        return sel

    def validate(self) -> None:
        ids = [i.id for i in self.all]
        qids = [i.qid for i in self.all]
        dup_ids = {i for i in ids if ids.count(i) > 1}
        dup_qids = {q for q in qids if qids.count(q) > 1}
        if dup_ids or dup_qids:
            raise ValueError(f"Duplicates in selection: ids={dup_ids} qids={dup_qids}")


def _str_values(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if v is not None else None) for k, v in d.items()}


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _label(ent: dict[str, Any], lang: str) -> str | None:
    value = ent.get("labels", {}).get(lang, {}).get("value")
    return str(value) if value else None


def _aliases(ent: dict[str, Any], lang: str) -> list[str]:
    return [str(a["value"]) for a in ent.get("aliases", {}).get(lang, [])]


def _claim_values(ent: dict[str, Any], prop: str) -> list[Any]:
    values = []
    for claim in ent.get("claims", {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        snak = claim.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        values.append(snak["datavalue"]["value"])
    return values


def _claim_qids(ent: dict[str, Any], prop: str) -> list[str]:
    return [str(v["id"]) for v in _claim_values(ent, prop) if isinstance(v, dict) and "id" in v]


def build_snapshot(client: WikidataClient, selection: Selection) -> dict[str, Any]:
    """Fetch everything we need for the selection in a few batched requests."""
    by_qid = {i.qid: i for i in selection.all}
    raw = client.get_entities(by_qid)

    records: list[dict[str, Any]] = []
    relations: list[dict[str, str]] = []
    seen_rel: set[tuple[str, str, str]] = set()

    def add_rel(src_qid: str, rel: str, dst_qid: str) -> None:
        if src_qid not in by_qid or dst_qid not in by_qid or src_qid == dst_qid:
            return
        src, dst = by_qid[src_qid].id, by_qid[dst_qid].id
        if rel == "spouse_of":  # symmetric: store once
            src, dst = sorted((src, dst))
        key = (src, rel, dst)
        if key not in seen_rel:
            seen_rel.add(key)
            relations.append(
                {"src_id": src, "rel": rel, "dst_id": dst, "source_ref": WIKIDATA_SOURCE}
            )

    for item in selection.all:
        ent = raw.get(item.qid)
        if not ent or "missing" in ent:
            records.append({"id": item.id, "qid": item.qid, "missing": True})
            continue

        rec: dict[str, Any] = {
            "id": item.id,
            "qid": item.qid,
            "type": item.type,
            "sitelinks": len(ent.get("sitelinks", {})),
            "label_uk": _label(ent, "uk"),
            "label_en": _label(ent, "en"),
            "label_la": _label(ent, "la"),
            "description_uk": ent.get("descriptions", {}).get("uk", {}).get("value"),
            "description_en": ent.get("descriptions", {}).get("en", {}).get("value"),
            "aliases_uk": _aliases(ent, "uk"),
            "aliases_en": _aliases(ent, "en"),
        }

        for parent in _claim_qids(ent, P_FATHER) + _claim_qids(ent, P_MOTHER):
            add_rel(parent, "parent_of", item.qid)
        for child in _claim_qids(ent, P_CHILD):
            add_rel(item.qid, "parent_of", child)
        for spouse in _claim_qids(ent, P_SPOUSE):
            add_rel(item.qid, "spouse_of", spouse)

        if item.type == "place":
            rec.update(_place_geo(client, ent, item))
        records.append(rec)

    return {
        "license": "Wikidata CC0; coordinates from Pleiades (CC BY) where available",
        "entities": records,
        "relations": relations,
    }


def _place_geo(client: WikidataClient, ent: dict[str, Any], item: SelectionItem) -> dict[str, Any]:
    pleiades_ids = [str(v) for v in _claim_values(ent, P_PLEIADES)]
    pid = item.pleiades_id or (pleiades_ids[0] if pleiades_ids else None)
    geo: dict[str, Any] = {"place_kind": item.place_kind, "pleiades_id": pid}
    if item.certainty == "none":  # mythical place: deliberately kept off the map
        geo["certainty"] = "none"
        return geo

    if pid:
        pl = client.get_pleiades(pid)
        point = (pl or {}).get("reprPoint")
        if point:
            geo.update(lat=round(float(point[1]), 5), lon=round(float(point[0]), 5))
            geo["coord_source"] = "pleiades"
            geo["pleiades_title"] = (pl or {}).get("title")
            return geo

    coords = [v for v in _claim_values(ent, P_COORD) if isinstance(v, dict)]
    if coords:
        geo.update(
            lat=round(float(coords[0]["latitude"]), 5),
            lon=round(float(coords[0]["longitude"]), 5),
            coord_source="wikidata",
        )
    return geo


# --------------------------------------------------------------------------- draft


def _load_yaml_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return list(data)


def _draft_aliases(rec: dict[str, Any]) -> list[dict[str, str]]:
    aliases: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    candidates = (
        [(rec.get("label_uk"), "uk")]
        + [(a, "uk") for a in rec.get("aliases_uk", [])]
        + [(rec.get("label_en"), "en")]
        + [(a, "en") for a in rec.get("aliases_en", [])]
        + [(rec.get("label_la"), "la")]
    )
    for alias, lang in candidates:
        if alias and (alias, lang) not in seen:
            seen.add((alias, lang))
            aliases.append({"alias": alias, "lang": lang})
    return aliases


def draft_entries(
    snapshot: dict[str, Any], seed_dir: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """New entities / places / relations that are not yet in the seed YAML."""
    existing_entities = {e["id"] for e in _load_yaml_list(seed_dir / "entities.yaml")}
    existing_places = {p["entity_id"] for p in _load_yaml_list(seed_dir / "places.yaml")}
    existing_rel = {
        (r["src_id"], r["rel"], r["dst_id"]) for r in _load_yaml_list(seed_dir / "relations.yaml")
    }

    new_entities: list[dict[str, Any]] = []
    new_places: list[dict[str, Any]] = []
    for rec in snapshot.get("entities", []):
        if rec.get("missing"):
            continue
        name_uk = rec.get("label_uk") or rec.get("label_en") or rec["id"]
        name_en = rec.get("label_en") or rec["id"]
        summary = rec.get("description_uk")
        if rec["type"] == "place":
            if rec["id"] in existing_places or rec["id"] in existing_entities:
                continue
            place: dict[str, Any] = {
                "entity_id": rec["id"],
                "name_uk": name_uk,
                "name_en": name_en,
                "place_kind": rec.get("place_kind") or "region",
                "wikidata_id": rec["qid"],
                "summary_uk": summary,
                "aliases": _draft_aliases(rec),
            }
            if rec.get("lat") is not None:
                place.update(
                    lat=rec["lat"],
                    lon=rec["lon"],
                    certainty=rec.get("certainty") or "high",
                    pleiades_id=int(rec["pleiades_id"]) if rec.get("pleiades_id") else None,
                )
            else:
                place["certainty"] = "none"
            new_places.append(place)
        else:
            if rec["id"] in existing_entities:
                continue
            new_entities.append(
                {
                    "id": rec["id"],
                    "type": rec["type"],
                    "name_uk": name_uk,
                    "name_en": name_en,
                    "name_lat": rec.get("label_la"),
                    "summary_uk": summary,
                    "domain": None,
                    "symbols": [],
                    "wikidata_id": rec["qid"],
                    "aliases": _draft_aliases(rec),
                }
            )

    new_relations = [
        r
        for r in snapshot.get("relations", [])
        if (r["src_id"], r["rel"], r["dst_id"]) not in existing_rel
        # spouse_of is symmetric
        and not (r["rel"] == "spouse_of" and (r["dst_id"], r["rel"], r["src_id"]) in existing_rel)
    ]
    return new_entities, new_places, new_relations


def append_yaml(path: Path, items: list[dict[str, Any]], header: str) -> None:
    """Append items as YAML text, keeping existing content and comments intact."""
    if not items:
        return
    text = yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=100)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n# --- {header} ---\n{text}")
