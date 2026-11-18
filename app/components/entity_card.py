import streamlit as st

from app.components.family_tree import render_family_tree
from delphi.encyclopedia.models import EntityCard


def render_entity_card(card: EntityCard):
    """Відображає детальну картку сутності."""
    st.subheader(f"{card.name_uk} ({card.name_en} / {card.name_lat or ''})")

    col1, col2 = st.columns([2, 1])

    with col1:
        if card.summary_uk:
            st.markdown(f"**Опис:** {card.summary_uk}")
        if card.domain:
            st.markdown(f"**Сфера впливу:** {card.domain}")
        if card.symbols:
            st.markdown(f"**Символи та атрибути:** {', '.join(card.symbols)}")

    with col2:
        st.markdown(f"**Тип:** `{card.type}`")
        if card.aliases:
            st.markdown(f"**Аліаси:** {', '.join(card.aliases[:4])}")
        if card.wikidata_id:
            st.caption(
                f"[Wikidata ({card.wikidata_id})](https://www.wikidata.org/wiki/{card.wikidata_id})"
            )

    # Граф родоводу
    if card.relations:
        st.markdown("##### 🌿 Родовід і зв'язки")
        render_family_tree(card.name_uk, card.relations)

    # Пов'язані міфи
    if card.myths:
        st.markdown("##### 🏛️ Пов'язані міфи")
        for m in card.myths:
            role = m.get("role", "учасник")
            summary = m.get("summary", "")
            st.markdown(f"- **{m['title']}** (роль: *{role}*): {summary}")

    st.markdown("---")
    btn_col1, btn_col2 = st.columns([1, 3])
    with btn_col1:
        if st.button(f"🔮 Запитати оракула про {card.name_uk}", key=f"ask_oracle_{card.id}"):
            st.session_state["pending_question"] = (
                f"Розкажи про {card.name_uk} та його роль у міфах"
            )
            st.session_state["active_tab"] = "Оракул"
            st.rerun()
