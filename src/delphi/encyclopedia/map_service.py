import math
from collections.abc import Iterable

from sqlmodel import Session, col, select

from delphi.db.models import Entity, Myth, MythEntity, Place, Relation, Route
from delphi.encyclopedia.models import (
    EntityRef,
    FilterOption,
    MapFilterOptions,
    MapLayer,
    MapMarker,
    MapRoute,
    MapRouteStop,
)
from delphi.encyclopedia.session import SessionMixin, entity_ref
from delphi.encyclopedia.vocab import PLACE_KINDS


class MapService(SessionMixin):
    """Map layers: place markers with filters, hero routes, mythical places off the map."""

    def get_map_layer(
        self,
        place_kind: str | None = None,
        place_kinds: Iterable[str] | None = None,
        god_id: str | None = None,
        myth_id: str | None = None,
        route_ids: Iterable[str] | None = None,
    ) -> MapLayer:
        kinds = set(place_kinds or ()) | ({place_kind} if place_kind else set())
        with self._use_session() as session:
            entities = {e.id: e for e in session.exec(select(Entity)).all()}
            patrons = _patrons(session, entities)

            stmt = select(Place)
            if kinds:
                stmt = stmt.where(col(Place.place_kind).in_(kinds))
            if god_id:
                worshipped = [p for p, gods in patrons.items() if any(g.id == god_id for g in gods)]
                stmt = stmt.where(col(Place.entity_id).in_(worshipped))
            if myth_id:
                stmt = stmt.where(col(Place.entity_id).in_(_myth_entity_ids(session, myth_id)))

            markers = []
            for p in session.exec(stmt).all():
                ent = entities.get(p.entity_id)
                markers.append(
                    MapMarker(
                        entity_id=p.entity_id,
                        name_uk=ent.name_uk if ent else p.entity_id,
                        place_kind=p.place_kind,
                        lat=p.lat,
                        lon=p.lon,
                        certainty=p.certainty,
                        summary_uk=ent.summary_uk if ent else None,
                        pleiades_id=p.pleiades_id,
                        patrons=patrons.get(p.entity_id, []),
                    )
                )
            markers.sort(key=lambda m: m.name_uk.lower())

            mapped = set(session.exec(select(Place.entity_id)).all())
            off_map = sorted(
                (
                    entity_ref(e)
                    for e in entities.values()
                    if e.type == "place" and e.id not in mapped
                ),
                key=lambda r: r.name_uk.lower(),
            )
            if myth_id:
                in_myth = _myth_entity_ids(session, myth_id)
                off_map = [r for r in off_map if r.id in in_myth]

            return MapLayer(
                markers=markers,
                routes=_routes(session, route_ids, myth_id),
                off_map=off_map,
            )

    def filter_options(self) -> MapFilterOptions:
        with self._use_session() as session:
            entities = {e.id: e for e in session.exec(select(Entity)).all()}
            kinds_present = set(session.exec(select(Place.place_kind)).all())
            god_ids = set(
                session.exec(select(Relation.src_id).where(Relation.rel == "worshipped_at")).all()
            )
            mapped = set(session.exec(select(Place.entity_id)).all())
            myth_ids = {
                me.myth_id
                for me in session.exec(select(MythEntity)).all()
                if me.entity_id in mapped
            }
            myths = session.exec(select(Myth).where(col(Myth.id).in_(myth_ids))).all()
            routes = session.exec(select(Route)).all()

            def by_label(options: list[FilterOption]) -> list[FilterOption]:
                return sorted(options, key=lambda o: o.label_uk.lower())

            return MapFilterOptions(
                place_kinds=[
                    FilterOption(id=k, label_uk=label)
                    for k, label in PLACE_KINDS.items()
                    if k in kinds_present
                ],
                gods=by_label(
                    [
                        FilterOption(id=g, label_uk=entities[g].name_uk)
                        for g in god_ids
                        if g in entities
                    ]
                ),
                myths=by_label([FilterOption(id=m.id, label_uk=m.title_uk) for m in myths]),
                routes=[FilterOption(id=r.id, label_uk=r.title_uk) for r in routes],
            )

    def nearest_place(self, lat: float, lon: float, max_km: float = 30.0) -> str | None:
        """Entity id of the mapped place nearest to a clicked point (within max_km)."""
        with self._use_session() as session:
            best: tuple[float, str] | None = None
            for p in session.exec(select(Place)).all():
                d = haversine_km(lat, lon, p.lat, p.lon)
                if best is None or d < best[0]:
                    best = (d, p.entity_id)
            if best is None or best[0] > max_km:
                return None
            return best[1]


def _patrons(session: Session, entities: dict[str, Entity]) -> dict[str, list[EntityRef]]:
    """place id -> gods worshipped there (relation worshipped_at)."""
    out: dict[str, list[EntityRef]] = {}
    for r in session.exec(select(Relation).where(Relation.rel == "worshipped_at")).all():
        if r.src_id in entities:
            refs = out.setdefault(r.dst_id, [])
            if all(ref.id != r.src_id for ref in refs):
                refs.append(entity_ref(entities[r.src_id]))
    return out


def _myth_entity_ids(session: Session, myth_id: str) -> set[str]:
    stmt = select(MythEntity.entity_id).where(MythEntity.myth_id == myth_id)
    return set(session.exec(stmt).all())


def _routes(
    session: Session, route_ids: Iterable[str] | None, myth_id: str | None
) -> list[MapRoute]:
    stmt = select(Route)
    if route_ids is not None:
        stmt = stmt.where(col(Route.id).in_(list(route_ids)))
    if myth_id:
        stmt = stmt.where(Route.myth_id == myth_id)
    routes = []
    for r in session.exec(stmt).all():
        stops = [
            MapRouteStop(
                stop_number=s.get("stop_number", idx + 1),
                entity_id=s.get("entity_id"),
                title=s.get("title", ""),
                lat=s.get("lat", 0.0),
                lon=s.get("lon", 0.0),
                certainty=s.get("certainty", "high"),
                source_ref=s.get("source_ref"),
                description=s.get("description"),
            )
            for idx, s in enumerate(r.stops)
        ]
        routes.append(
            MapRoute(
                id=r.id,
                title_uk=r.title_uk,
                hero_id=r.hero_id,
                myth_id=r.myth_id,
                description_uk=r.description_uk,
                stops=stops,
            )
        )
    return routes


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
