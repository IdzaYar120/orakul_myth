"""Cross-tab navigation state (st.session_state + ?entity= query param)."""

import streamlit as st

TABS = ["Оракул", "Енциклопедія", "Карта"]


def go_to_tab(tab: str) -> None:
    st.session_state["active_tab"] = tab


def open_entity(entity_id: str) -> None:
    """Open an entity card in the encyclopedia; the URL becomes shareable (?entity=id)."""
    st.session_state["selected_entity"] = entity_id
    st.query_params["entity"] = entity_id
    go_to_tab("Енциклопедія")


def close_entity() -> None:
    st.session_state.pop("selected_entity", None)
    if "entity" in st.query_params:
        del st.query_params["entity"]


def ask_oracle(question: str) -> None:
    st.session_state["pending_question"] = question
    go_to_tab("Оракул")
