import streamlit as st

from app.components.entity_card import render_entity_card
from delphi.encyclopedia.service import EncyclopediaService


def render_encyclopedia_tab(service: EncyclopediaService):
    st.header("📖 Антична енциклопедія")
    st.caption("Швидкий довідник богів, героїв, місць та міфологічних зв'язків без залучення ШІ.")

    col1, col2 = st.columns([3, 1])
    with col1:
        search_query = st.text_input("Пошук сутності (українською, англійською або латиною):", "")
    with col2:
        type_filter = st.selectbox(
            "Фільтр за типом:",
            options=["всі", "god", "titan", "hero", "place", "creature"],
            index=0,
        )

    # If a specific entity is selected (via click or URL)
    selected_id = st.session_state.get("selected_entity")

    if search_query:
        cards = service.search(search_query)
        if type_filter != "всі":
            cards = [c for c in cards if c.type == type_filter]

        if not cards:
            st.warning(f"Сутностей за запитом «{search_query}» не знайдено.")
        else:
            st.write(f"Знайдено: {len(cards)}")
            for c in cards:
                render_entity_card(c)
    elif selected_id:
        card = service.get_entity_card(selected_id)
        if card:
            render_entity_card(card)
        else:
            st.error(f"Сутність з ID '{selected_id}' не знайдена.")
    else:
        # Display available entities list
        actual_filter = None if type_filter == "всі" else type_filter
        entities = service.list_entities(entity_type=actual_filter)
        if not entities:
            st.info("База даних порожня. Запустіть `delphi seed` для наповнення даними.")
        else:
            st.markdown("##### Оберіть сутність зі списку:")
            cols = st.columns(3)
            for idx, ent in enumerate(entities):
                with cols[idx % 3]:
                    if st.button(f"{ent.name_uk} ({ent.name_en})", key=f"ent_btn_{ent.id}"):
                        st.session_state["selected_entity"] = ent.id
                        st.rerun()
