import streamlit as st

from app.pages.encyclopedia import render_encyclopedia_tab
from app.pages.map import render_map_tab
from app.pages.oracle import render_oracle_tab
from delphi.db.repo import init_db
from delphi.encyclopedia.service import EncyclopediaService, MapService
from delphi.rag.oracle import OracleService

# Streamlit page setup
st.set_page_config(
    page_title="Дельфійський оракул",
    page_icon="🔮",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_services():
    """Initializes database and caches service instances once."""
    init_db()
    encyclopedia_svc = EncyclopediaService()
    map_svc = MapService()
    oracle_svc = OracleService()
    return encyclopedia_svc, map_svc, oracle_svc


def main():
    encyclopedia_svc, map_svc, oracle_svc = get_services()

    # Handle URL query params (?entity=...)
    query_params = st.query_params
    if "entity" in query_params and "selected_entity" not in st.session_state:
        st.session_state["selected_entity"] = query_params["entity"]

    # Sidebar
    with st.sidebar:
        st.title("🏛️ Дельфи")
        st.markdown(
            """
            **Дельфійський оракул** — система дослідження давньогрецької міфології:
            - **Оракул**: RAG-чат на базі античних текстів із посиланнями.
            - **Енциклопедія**: структуровані картки богів, героїв та місць.
            - **Карта**: географія античності та маршрути міфів.
            """
        )
        st.divider()

        # Active tab selection
        tab_options = ["Оракул", "Енциклопедія", "Карта"]
        default_index = 0
        if "active_tab" in st.session_state and st.session_state["active_tab"] in tab_options:
            default_index = tab_options.index(st.session_state["active_tab"])

        chosen_tab = st.radio(
            "Розділи:",
            tab_options,
            index=default_index,
            key="navigation_radio",
        )
        st.session_state["active_tab"] = chosen_tab

        st.divider()
        st.caption("Версія: 0.1.0 (MVP Stage 0: Skeleton)")

    # Render selected tab
    if chosen_tab == "Оракул":
        render_oracle_tab(oracle_svc)
    elif chosen_tab == "Енциклопедія":
        render_encyclopedia_tab(encyclopedia_svc)
    elif chosen_tab == "Карта":
        render_map_tab(map_svc)


if __name__ == "__main__":
    main()
