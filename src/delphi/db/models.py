import json
from typing import Any, cast

from sqlmodel import Field, SQLModel


class Entity(SQLModel, table=True):
    __tablename__ = "entity"

    id: str = Field(primary_key=True, index=True)
    type: str = Field(index=True)  # god, titan, hero, mortal, creature, place, artifact
    name_uk: str = Field(index=True)
    name_en: str = Field(index=True)
    name_lat: str | None = None
    summary_uk: str | None = None
    domain: str | None = None
    symbols_json: str | None = Field(default="[]")
    wikidata_id: str | None = None

    @property
    def symbols(self) -> list[str]:
        if not self.symbols_json:
            return []
        try:
            val = json.loads(self.symbols_json)
            return cast(list[str], val) if isinstance(val, list) else []
        except Exception:
            return []

    @symbols.setter
    def symbols(self, val: list[str]) -> None:
        self.symbols_json = json.dumps(val, ensure_ascii=False)


class Place(SQLModel, table=True):
    __tablename__ = "place"

    entity_id: str = Field(primary_key=True, foreign_key="entity.id")
    lat: float
    lon: float
    place_kind: str = Field(index=True)  # sanctuary, city, mountain, island, river, region
    pleiades_id: int | None = None
    certainty: str = "high"  # high, medium, low


class Alias(SQLModel, table=True):
    __tablename__ = "alias"

    id: int | None = Field(default=None, primary_key=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    alias: str = Field(index=True)
    lang: str = Field(default="uk")  # uk, en, la, el


class Relation(SQLModel, table=True):
    __tablename__ = "relation"

    id: int | None = Field(default=None, primary_key=True)
    src_id: str = Field(index=True)
    rel: str = Field(index=True)  # parent_of, spouse_of, sibling_of, killed, worshipped_at, born_at
    dst_id: str = Field(index=True)
    source_ref: str


class Myth(SQLModel, table=True):
    __tablename__ = "myth"

    id: str = Field(primary_key=True, index=True)
    title_uk: str
    summary_uk: str
    cycle: str = Field(index=True)  # trojan, theban, argonauts, teogoniya


class MythEntity(SQLModel, table=True):
    __tablename__ = "myth_entity"

    id: int | None = Field(default=None, primary_key=True)
    myth_id: str = Field(foreign_key="myth.id", index=True)
    entity_id: str = Field(foreign_key="entity.id", index=True)
    role: str = "participant"


class Route(SQLModel, table=True):
    __tablename__ = "route"

    id: str = Field(primary_key=True, index=True)
    title_uk: str
    hero_id: str | None = Field(default=None, foreign_key="entity.id", index=True)
    description_uk: str | None = None
    stops_json: str = "[]"

    @property
    def stops(self) -> list[dict[str, Any]]:
        if not self.stops_json:
            return []
        try:
            val = json.loads(self.stops_json)
            return cast(list[dict[str, Any]], val) if isinstance(val, list) else []
        except Exception:
            return []

    @stops.setter
    def stops(self, val: list[dict[str, Any]]) -> None:
        self.stops_json = json.dumps(val, ensure_ascii=False)


class Passage(SQLModel, table=True):
    __tablename__ = "passage"

    id: str = Field(primary_key=True, index=True)  # hash(work + ref)
    work: str = Field(index=True)
    author: str = Field(index=True)
    translator: str
    ref: str = Field(index=True)
    text: str
    n_tokens: int = 0


class PassageEntity(SQLModel, table=True):
    __tablename__ = "passage_entity"

    passage_id: str = Field(primary_key=True, foreign_key="passage.id")
    entity_id: str = Field(primary_key=True, foreign_key="entity.id")
