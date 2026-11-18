from pydantic import BaseModel, Field


class EntityRef(BaseModel):
    """Lightweight reference to an entity (search results, links on a card)."""

    id: str
    type: str
    name_uk: str
    name_en: str
    summary_uk: str | None = None


class RelatedEntity(BaseModel):
    """One related entity with all sources that attest the relation.

    Several sources (versions of a myth) are kept side by side, e.g. Aphrodite's
    parents per Hesiod vs. Homer.
    """

    entity: EntityRef
    source_refs: list[str] = Field(default_factory=list)
    verified: bool = False  # at least one source_ref points to an ancient text


class RelationGroup(BaseModel):
    rel: str
    direction: str  # "out" (card entity is src) | "in" (card entity is dst)
    label_uk: str
    items: list[RelatedEntity] = Field(default_factory=list)


class SiblingGroup(BaseModel):
    """Half-siblings through one shared parent."""

    via: EntityRef
    items: list[RelatedEntity] = Field(default_factory=list)


class Lineage(BaseModel):
    parents: list[RelatedEntity] = Field(default_factory=list)
    spouses: list[RelatedEntity] = Field(default_factory=list)
    children: list[RelatedEntity] = Field(default_factory=list)
    # Derived from shared parents: full siblings share two or more of the parents
    siblings: list[RelatedEntity] = Field(default_factory=list)
    half_siblings: list[SiblingGroup] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.parents or self.spouses or self.children or self.siblings or self.half_siblings
        )


class EntityRelationItem(BaseModel):
    """Flat relation record (kept for simple consumers such as the CLI)."""

    rel: str
    target_id: str
    target_name_uk: str
    source_ref: str


class MythRef(BaseModel):
    id: str
    title_uk: str
    cycle: str
    role: str
    summary_uk: str
    participants: list[EntityRef] = Field(default_factory=list)


class PassageRef(BaseModel):
    work: str
    author: str
    ref: str
    text: str


class MapMarker(BaseModel):
    entity_id: str
    name_uk: str
    place_kind: str
    lat: float
    lon: float
    certainty: str = "high"
    summary_uk: str | None = None
    pleiades_id: int | None = None
    relation_label: str | None = None  # why this place is shown on an entity card
    patrons: list[EntityRef] = Field(default_factory=list)  # gods worshipped here


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
    lineage: Lineage = Field(default_factory=Lineage)
    other_relations: list[RelationGroup] = Field(default_factory=list)
    relations: list[EntityRelationItem] = Field(default_factory=list)  # outgoing, flat
    place: MapMarker | None = None  # coordinates, if the entity is a mapped place
    places: list[MapMarker] = Field(default_factory=list)  # related places for the mini-map
    myths: list[MythRef] = Field(default_factory=list)
    cycles: list[str] = Field(default_factory=list)
    passages: list[PassageRef] = Field(default_factory=list)


class MapRouteStop(BaseModel):
    stop_number: int
    entity_id: str | None = None  # some stops (e.g. Lotus-eaters) have no encyclopedia card
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
    myth_id: str | None = None
    description_uk: str | None = None
    stops: list[MapRouteStop] = Field(default_factory=list)

    @property
    def is_speculative(self) -> bool:
        """True if any stop is only a traditional identification."""
        return any(s.certainty != "high" for s in self.stops)


class MapLayer(BaseModel):
    markers: list[MapMarker] = Field(default_factory=list)
    routes: list[MapRoute] = Field(default_factory=list)
    off_map: list[EntityRef] = Field(default_factory=list)  # mythical places without location


class FilterOption(BaseModel):
    id: str
    label_uk: str


class MapFilterOptions(BaseModel):
    place_kinds: list[FilterOption] = Field(default_factory=list)
    gods: list[FilterOption] = Field(default_factory=list)  # gods with worshipped_at places
    myths: list[FilterOption] = Field(default_factory=list)  # myths with mapped places
    routes: list[FilterOption] = Field(default_factory=list)
