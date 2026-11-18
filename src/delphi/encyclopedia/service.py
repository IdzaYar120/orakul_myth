from collections.abc import Generator, Iterable
from contextlib import contextmanager

from sqlmodel import Session, col, or_, select

from delphi.db.models import (
    Alias,
    Entity,
    Myth,
    MythEntity,
    Passage,
    PassageEntity,
    Place,
    Relation,
    Route,
)
from delphi.db.repo import engine
from delphi.encyclopedia.models import (
    EntityCard,
    EntityRef,
    EntityRelationItem,
    Lineage,
    MapLayer,
    MapMarker,
    MapRoute,
    MapRouteStop,
    MythRef,
    PassageRef,
    RelatedEntity,
    RelationGroup,
    SiblingGroup,
)
from delphi.encyclopedia.search import search_entities
from delphi.encyclopedia.vocab import RELATION_LABELS, is_verified

LINEAGE_RELS = {"parent_of", "spouse_of", "sibling_of"}
PLACE_RELS = {"worshipped_at", "born_at", "ruled"}
MAX_PASSAGES = 5


class _SessionMixin:
    def __init__(self, session: Session | None = None):
        self._session = session

    @contextmanager
    def _use_session(self, session: Session | None = None) -> Generator[Session]:
        """Use the injected/explicit session, or open (and close) a short-lived one."""
        if session is not None:
            yield session
        elif self._session is not None:
            yield self._session
        else:
            with Session(engine) as sess:
                yield sess


def _ref(e: Entity) -> EntityRef:
    return EntityRef(
        id=e.id, type=e.type, name_uk=e.name_uk, name_en=e.name_en, summary_uk=e.summary_uk
    )


def _related(pairs: Iterable[tuple[str, str]], entities: dict[str, Entity]) -> list[RelatedEntity]:
    """Group (entity_id, source_ref) pairs into RelatedEntity items, keeping order."""
    grouped: dict[str, list[str]] = {}
    for eid, ref in pairs:
        refs = grouped.setdefault(eid, [])
        if ref not in refs:
            refs.append(ref)
    items = []
    for eid, refs in grouped.items():
        ent = entities.get(eid)
        if ent is None:
            continue
        items.append(
            RelatedEntity(
                entity=_ref(ent),
                source_refs=refs,
                verified=any(is_verified(r) for r in refs),
            )
        )
    return items


class EncyclopediaService(_SessionMixin):
    """Entity search and cards. SQLite only — works without an LLM or API key."""

    # ------------------------------------------------------------------ search
    def search(
        self,
        query: str,
        entity_type: str | None = None,
        cycle: str | None = None,
        limit: int = 50,
    ) -> list[EntityRef]:
        with self._use_session() as session:
            ids = search_entities(query, session=session, limit=max(limit * 2, 40))
            if not ids:
                return []
            allowed = self._filter_ids(session, ids, entity_type, cycle)
            entities = {
                e.id: e for e in session.exec(select(Entity).where(col(Entity.id).in_(ids)))
            }
            return [_ref(entities[i]) for i in ids if i in allowed and i in entities][:limit]

    def list_entities(
        self, entity_type: str | None = None, cycle: str | None = None
    ) -> list[EntityRef]:
        with self._use_session() as session:
            stmt = select(Entity)
            if entity_type:
                stmt = stmt.where(Entity.type == entity_type)
            if cycle:
                stmt = stmt.where(col(Entity.id).in_(self._cycle_entity_ids(session, cycle)))
            entities = session.exec(stmt).all()
            return sorted((_ref(e) for e in entities), key=lambda r: r.name_uk.lower())

    def _filter_ids(
        self, session: Session, ids: list[str], entity_type: str | None, cycle: str | None
    ) -> set[str]:
        allowed = set(ids)
        if entity_type:
            typed = session.exec(
                select(Entity.id).where(col(Entity.id).in_(ids), Entity.type == entity_type)
            ).all()
            allowed &= set(typed)
        if cycle:
            allowed &= self._cycle_entity_ids(session, cycle)
        return allowed

    @staticmethod
    def _cycle_entity_ids(session: Session, cycle: str) -> set[str]:
        stmt = (
            select(MythEntity.entity_id)
            .join(Myth, col(Myth.id) == col(MythEntity.myth_id))
            .where(Myth.cycle == cycle)
        )
        return set(session.exec(stmt).all())

    # ------------------------------------------------------------------ card
    def get_entity_card(self, entity_id: str, session: Session | None = None) -> EntityCard | None:
        with self._use_session(session) as sess:
            entity = sess.get(Entity, entity_id)
            if entity is None:
                return None

            entities = {e.id: e for e in sess.exec(select(Entity)).all()}
            aliases = list(
                dict.fromkeys(
                    a.alias for a in sess.exec(select(Alias).where(Alias.entity_id == entity_id))
                )
            )
            rels = sess.exec(
                select(Relation).where(
                    or_(Relation.src_id == entity_id, Relation.dst_id == entity_id)
                )
            ).all()

            lineage = self._lineage(sess, entity_id, rels, entities)
            other = self._other_relations(entity_id, rels, entities)
            place = self._marker(sess, entity_id, entities)
            places = self._related_places(sess, entity_id, rels, entities)
            myths = self._myths(sess, entity_id, entities)

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
                lineage=lineage,
                other_relations=other,
                relations=[
                    EntityRelationItem(
                        rel=r.rel,
                        target_id=r.dst_id,
                        target_name_uk=entities[r.dst_id].name_uk
                        if r.dst_id in entities
                        else r.dst_id,
                        source_ref=r.source_ref,
                    )
                    for r in rels
                    if r.src_id == entity_id
                ],
                place=place,
                places=places,
                myths=myths,
                cycles=list(dict.fromkeys(m.cycle for m in myths)),
                passages=self._passages(sess, entity_id),
            )

    @staticmethod
    def _lineage(
        session: Session, entity_id: str, rels: Iterable[Relation], entities: dict[str, Entity]
    ) -> Lineage:
        rels = list(rels)
        parents = [
            (r.src_id, r.source_ref) for r in rels if r.rel == "parent_of" and r.dst_id == entity_id
        ]
        children = [
            (r.dst_id, r.source_ref) for r in rels if r.rel == "parent_of" and r.src_id == entity_id
        ]
        spouses = [
            (r.dst_id if r.src_id == entity_id else r.src_id, r.source_ref)
            for r in rels
            if r.rel == "spouse_of"
        ]
        siblings = [
            (r.dst_id if r.src_id == entity_id else r.src_id, r.source_ref)
            for r in rels
            if r.rel == "sibling_of"
        ]

        # Derived siblings: other children of the parents. Several parents can come from
        # different versions of a myth, so "full" siblings must share 2+ of them.
        parent_ids = list(dict.fromkeys(p for p, _ in parents))
        via_parent: dict[str, list[tuple[str, str]]] = {}
        if parent_ids:
            for r in session.exec(
                select(Relation).where(
                    Relation.rel == "parent_of",
                    col(Relation.src_id).in_(parent_ids),
                    Relation.dst_id != entity_id,
                )
            ).all():
                via_parent.setdefault(r.src_id, []).append((r.dst_id, r.source_ref))
        shared: dict[str, int] = {}
        for pairs in via_parent.values():
            for sib in {s for s, _ in pairs}:
                shared[sib] = shared.get(sib, 0) + 1
        full_ids = {s for s, n in shared.items() if n >= 2}
        siblings += [pair for pairs in via_parent.values() for pair in pairs if pair[0] in full_ids]
        explicit = {s for s, _ in siblings}

        def by_name(items: list[RelatedEntity]) -> list[RelatedEntity]:
            return sorted(items, key=lambda i: i.entity.name_uk.lower())

        half: list[SiblingGroup] = []
        for pid in parent_ids:
            pairs = [p for p in via_parent.get(pid, []) if p[0] not in explicit]
            if pairs and pid in entities:
                half.append(
                    SiblingGroup(via=_ref(entities[pid]), items=by_name(_related(pairs, entities)))
                )

        return Lineage(
            parents=_related(parents, entities),
            spouses=_related(spouses, entities),
            children=by_name(_related(children, entities)),
            siblings=by_name(_related(siblings, entities)),
            half_siblings=half,
        )

    @staticmethod
    def _other_relations(
        entity_id: str, rels: Iterable[Relation], entities: dict[str, Entity]
    ) -> list[RelationGroup]:
        groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for r in rels:
            if r.rel in LINEAGE_RELS:
                continue
            direction = "out" if r.src_id == entity_id else "in"
            other = r.dst_id if direction == "out" else r.src_id
            groups.setdefault((r.rel, direction), []).append((other, r.source_ref))
        out = []
        for (rel, direction), pairs in groups.items():
            labels = RELATION_LABELS.get(rel, (rel, rel))
            out.append(
                RelationGroup(
                    rel=rel,
                    direction=direction,
                    label_uk=labels[0] if direction == "out" else labels[1],
                    items=_related(pairs, entities),
                )
            )
        return out

    @staticmethod
    def _marker(
        session: Session, entity_id: str, entities: dict[str, Entity], label: str | None = None
    ) -> MapMarker | None:
        place = session.get(Place, entity_id)
        ent = entities.get(entity_id)
        if place is None or ent is None:
            return None
        return MapMarker(
            entity_id=entity_id,
            name_uk=ent.name_uk,
            place_kind=place.place_kind,
            lat=place.lat,
            lon=place.lon,
            certainty=place.certainty,
            summary_uk=ent.summary_uk,
            pleiades_id=place.pleiades_id,
            relation_label=label,
        )

    def _related_places(
        self,
        session: Session,
        entity_id: str,
        rels: Iterable[Relation],
        entities: dict[str, Entity],
    ) -> list[MapMarker]:
        """Places linked by relations; for a place: the people/gods linked to it are listed
        in other_relations, and the mini-map shows the place itself."""
        markers: dict[str, MapMarker] = {}
        for r in rels:
            if r.rel not in PLACE_RELS or r.src_id != entity_id:
                continue
            label = RELATION_LABELS[r.rel][0]
            if r.dst_id in markers:
                continue
            marker = self._marker(session, r.dst_id, entities, label)
            if marker:
                markers[r.dst_id] = marker
        own = self._marker(session, entity_id, entities)
        if own:
            markers.setdefault(entity_id, own)
        return list(markers.values())

    @staticmethod
    def _myths(session: Session, entity_id: str, entities: dict[str, Entity]) -> list[MythRef]:
        links = session.exec(select(MythEntity).where(MythEntity.entity_id == entity_id)).all()
        myths = []
        for link in links:
            myth = session.get(Myth, link.myth_id)
            if myth is None:
                continue
            participant_ids = session.exec(
                select(MythEntity.entity_id).where(
                    MythEntity.myth_id == myth.id, MythEntity.entity_id != entity_id
                )
            ).all()
            myths.append(
                MythRef(
                    id=myth.id,
                    title_uk=myth.title_uk,
                    cycle=myth.cycle,
                    role=link.role,
                    summary_uk=myth.summary_uk,
                    participants=[_ref(entities[p]) for p in participant_ids if p in entities],
                )
            )
        return myths

    @staticmethod
    def _passages(session: Session, entity_id: str) -> list[PassageRef]:
        """3-5 passages mentioning the entity (populated by `delphi ingest`, Stage 3)."""
        stmt = (
            select(Passage)
            .join(PassageEntity, col(PassageEntity.passage_id) == col(Passage.id))
            .where(PassageEntity.entity_id == entity_id)
            .limit(MAX_PASSAGES)
        )
        return [
            PassageRef(work=p.work, author=p.author, ref=p.ref, text=p.text)
            for p in session.exec(stmt).all()
        ]


class MapService(_SessionMixin):
    def get_map_layer(self, place_kind: str | None = None) -> MapLayer:
        with self._use_session() as session:
            stmt = select(Place)
            if place_kind:
                stmt = stmt.where(Place.place_kind == place_kind)
            places = session.exec(stmt).all()
            entities = {e.id: e for e in session.exec(select(Entity)).all()}

            markers = []
            for p in places:
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
                    )
                )

            routes = []
            for r in session.exec(select(Route)).all():
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
