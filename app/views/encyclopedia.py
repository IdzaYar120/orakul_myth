import streamlit as st

from app.components.entity_card import render_entity_card
from app.components.navigation import close_entity, open_entity
from delphi.encyclopedia.models import EntityRef
from delphi.encyclopedia.service import EncyclopediaService
from delphi.encyclopedia.vocab import ENTITY_TYPES, MYTH_CYCLES

GRID_COLUMNS = 3
MAX_RESULTS = 60


def render_encyclopedia_tab(service: EncyclopediaService):
    st.header("📖 Антична енциклопедія")
    st.caption("Боги, герої, істоти та місця з родоводами й джерелами — без залучення ШІ.")

    selected_id = st.session_state.get("selected_entity")
    if selected_id:
        st.button("← До пошуку", on_click=close_entity, key="enc_back")
        card = service.get_entity_card(selected_id)
        if card:
            render_entity_card(card)
        else:
            st.error(f"Сутність з ID «{selected_id}» не знайдена.")
        return

    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        query = st.text_input(
            "Пошук (українською, англійською або латиною):",
            key="enc_query",
            placeholder="напр. Персефона, Ulysses, Jupiter, Дельфи",
        )
    with col2:
        entity_type = st.selectbox(
            "Тип:",
            options=[None, *ENTITY_TYPES],
            format_func=lambda t: "усі" if t is None else ENTITY_TYPES[t],
            key="enc_type",
        )
    with col3:
        cycle = st.selectbox(
            "Цикл міфів:",
            options=[None, *MYTH_CYCLES],
            format_func=lambda c: "усі" if c is None else MYTH_CYCLES[c],
            key="enc_cycle",
        )

    if query.strip():
        results = service.search(query, entity_type=entity_type, cycle=cycle, limit=MAX_RESULTS)
        if not results:
            st.warning(f"За запитом «{query}» нічого не знайдено.")
            return
        st.caption(f"Знайдено: {len(results)}")
        _grid(results, key_prefix="res")
        return

    entities = service.list_entities(entity_type=entity_type, cycle=cycle)
    if not entities:
        if entity_type or cycle:
            st.info("Немає сутностей з такими фільтрами.")
        else:
            st.info("База даних порожня. Запустіть `delphi seed` для наповнення даними.")
        return

    st.caption(f"Усього: {len(entities)}")
    for typ, label in ENTITY_TYPES.items():
        group = [e for e in entities if e.type == typ]
        if group:
            with st.expander(f"{label} ({len(group)})", expanded=bool(entity_type or cycle)):
                _grid(group, key_prefix=f"list_{typ}")


def _grid(entities: list[EntityRef], key_prefix: str) -> None:
    cols = st.columns(GRID_COLUMNS)
    for idx, ent in enumerate(entities):
        with cols[idx % GRID_COLUMNS]:
            st.button(
                f"{ent.name_uk} · {ent.name_en}",
                key=f"{key_prefix}_{ent.id}",
                help=ent.summary_uk,
                on_click=open_entity,
                args=(ent.id,),
                width="stretch",
            )
