from pydantic import BaseModel, Field


class EntityRelationItem(BaseModel):
    rel: str
    target_id: str
    target_name_uk: str
    source_ref: str


class EntityCard(BaseModel):
    id: str
    type: str
    name_uk: str
    name_en: str
    name_lat: str | None = None
    summary_uk: str | None = None
    domain: str | None = None
    symbols: list[str] = Field(default_factory=list)
    wikidata_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    relations: list[EntityRelationItem] = Field(default_factory=list)
    myths: list[dict[str, str]] = Field(default_factory=list)
    passages: list[dict[str, str]] = Field(default_factory=list)


class MapMarker(BaseModel):
    entity_id: str
    name_uk: str
    place_kind: str
    lat: float
    lon: float
    certainty: str = "high"
    summary_uk: str | None = None
    pleiades_id: int | None = None


class MapRouteStop(BaseModel):
    stop_number: int
    entity_id: str
    title: str
    lat: float
    lon: float
    certainty: str = "high"
    source_ref: str | None = None
    description: str | None = None


class MapRoute(BaseModel):
    id: str
    title_uk: str
    hero_id: str | None = None
    description_uk: str | None = None
    stops: list[MapRouteStop] = Field(default_factory=list)


class MapLayer(BaseModel):
    markers: list[MapMarker] = Field(default_factory=list)
    routes: list[MapRoute] = Field(default_factory=list)
