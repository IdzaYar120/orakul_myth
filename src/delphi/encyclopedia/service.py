from sqlmodel import Session, select

from delphi.db.models import (
    Alias,
    Entity,
    Myth,
    MythEntity,
    Place,
    Relation,
    Route,
)
from delphi.db.repo import engine
from delphi.encyclopedia.models import (
    EntityCard,
    EntityRelationItem,
    MapLayer,
    MapMarker,
    MapRoute,
    MapRouteStop,
)
from delphi.encyclopedia.search import search_entities


class EncyclopediaService:
    def __init__(self, session: Session | None = None):
        self._session = session

    def _get_session(self) -> Session:
        return self._session or Session(engine)

    def search(self, query: str) -> list[EntityCard]:
        session = self._get_session()
        try:
            ids = search_entities(query, session=session)
            cards = []
            for eid in ids:
                card = self.get_entity_card(eid, session=session)
                if card:
                    cards.append(card)
            return cards
        finally:
            if self._session is None:
                session.close()

    def list_entities(self, entity_type: str | None = None) -> list[Entity]:
        session = self._get_session()
        try:
            stmt = select(Entity)
            if entity_type:
                stmt = stmt.where(Entity.type == entity_type)
            return list(session.exec(stmt).all())
        finally:
            if self._session is None:
                session.close()

    def get_entity_card(self, entity_id: str, session: Session | None = None) -> EntityCard | None:
        sess = session or self._get_session()
        try:
            entity = sess.get(Entity, entity_id)
            if not entity:
                return None

            # Аліаси
            aliases = [
                a.alias for a in sess.exec(select(Alias).where(Alias.entity_id == entity_id)).all()
            ]

            # Зв'язки
            relations_out: list[EntityRelationItem] = []
            rel_records = sess.exec(select(Relation).where(Relation.src_id == entity_id)).all()
            for r in rel_records:
                target = sess.get(Entity, r.dst_id)
                target_name = target.name_uk if target else r.dst_id
                relations_out.append(
                    EntityRelationItem(
                        rel=r.rel,
                        target_id=r.dst_id,
                        target_name_uk=target_name,
                        source_ref=r.source_ref,
                    )
                )

            # Міфи
            myths_list: list[dict[str, str]] = []
            myth_links = sess.exec(
                select(MythEntity).where(MythEntity.entity_id == entity_id)
            ).all()
            for ml in myth_links:
                m = sess.get(Myth, ml.myth_id)
                if m:
                    myths_list.append(
                        {
                            "id": m.id,
                            "title": m.title_uk,
                            "role": ml.role,
                            "summary": m.summary_uk,
                        }
                    )

            return EntityCard(
                id=entity.id,
                type=entity.type,
                name_uk=entity.name_uk,
                name_en=entity.name_en,
                name_lat=entity.name_lat,
                summary_uk=entity.summary_uk,
                domain=entity.domain,
                symbols=entity.symbols,
                wikidata_id=entity.wikidata_id,
                aliases=aliases,
                relations=relations_out,
                myths=myths_list,
                passages=[],
            )
        finally:
            if session is None and self._session is None:
                sess.close()


class MapService:
    def __init__(self, session: Session | None = None):
        self._session = session

    def _get_session(self) -> Session:
        return self._session or Session(engine)

    def get_map_layer(self, place_kind: str | None = None) -> MapLayer:
        session = self._get_session()
        try:
            stmt = select(Place)
            if place_kind:
                stmt = stmt.where(Place.place_kind == place_kind)
            places = session.exec(stmt).all()

            markers = []
            for p in places:
                ent = session.get(Entity, p.entity_id)
                name_uk = ent.name_uk if ent else p.entity_id
                summary_uk = ent.summary_uk if ent else None
                markers.append(
                    MapMarker(
                        entity_id=p.entity_id,
                        name_uk=name_uk,
                        place_kind=p.place_kind,
                        lat=p.lat,
                        lon=p.lon,
                        certainty=p.certainty,
                        summary_uk=summary_uk,
                        pleiades_id=p.pleiades_id,
                    )
                )

            routes_data = session.exec(select(Route)).all()
            routes = []
            for r in routes_data:
                stops = [
                    MapRouteStop(
                        stop_number=s.get("stop_number", idx + 1),
                        entity_id=s.get("entity_id", ""),
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
                        description_uk=r.description_uk,
                        stops=stops,
                    )
                )

            return MapLayer(markers=markers, routes=routes)
        finally:
            if self._session is None:
                session.close()
