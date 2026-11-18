import re

from rapidfuzz import fuzz, process
from sqlmodel import Session, col, select

from delphi.db.models import Alias, Entity
from delphi.db.repo import engine


class EntityLinker:
    """Знаходить згадані у запитанні українські назви та додає англійські форми."""

    def __init__(self, session: Session | None = None):
        self._session = session

    def _get_session(self) -> Session:
        return self._session or Session(engine)

    def extract_and_expand(self, question: str) -> tuple[list[str], list[str]]:
        """
        Знаходить в питанні сутності.
        Повертає:
          (found_entity_ids, english_aliases_for_expansion)
        """
        session = self._get_session()
        try:
            # Витягуємо всі аліаси
            aliases = session.exec(select(Alias)).all()
            if not aliases:
                return [], []

            # Пошук слів у запитанні
            words = re.findall(r"\b\w{3,}\b", question, flags=re.UNICODE)
            found_ids: set[str] = set()

            alias_map: dict[str, str] = {a.alias.lower(): a.entity_id for a in aliases}
            all_alias_names = list(alias_map.keys())

            for word in words:
                matches = process.extract(
                    word.lower(),
                    all_alias_names,
                    scorer=fuzz.ratio,
                    limit=2,
                    score_cutoff=80,
                )
                for matched_name, _, _ in matches:
                    found_ids.add(alias_map[matched_name])

            # Для знайдених id шукаємо англійські аліаси
            expansion_terms: list[str] = []
            for eid in found_ids:
                en_aliases = session.exec(
                    select(Alias.alias).where(
                        Alias.entity_id == eid,
                        col(Alias.lang).in_(["en", "la"]),
                    )
                ).all()
                expansion_terms.extend(en_aliases)

            return list(found_ids), list(set(expansion_terms))
        finally:
            if self._session is None:
                session.close()

    def get_glossary_for_entities(self, entity_ids: list[str]) -> str:
        """Повертає рядок словника перекладу для промпту: Achilles -> Ахілл, Apollo -> Аполлон."""
        if not entity_ids:
            return "Загальноприйняті норми українського правопису античних імен."

        session = self._get_session()
        try:
            items = []
            for eid in entity_ids:
                ent = session.get(Entity, eid)
                if ent:
                    items.append(f"{ent.name_en} -> {ent.name_uk}")
            return ", ".join(items)
        finally:
            if self._session is None:
                session.close()
