import sys
from pathlib import Path

# `streamlit run app/main.py` only puts `app/` on sys.path; add the repo root
# so that `app.*` imports resolve (the `delphi` package is installed via uv).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402

from app.components.navigation import (  # noqa: E402
    TAB_SLUGS,
    TABS,
    go_to_tab,
    open_entity,
    show_on_map,
)
from app.views.encyclopedia import render_encyclopedia_tab  # noqa: E402
from app.views.map import render_map_tab  # noqa: E402
from app.views.oracle import render_oracle_tab  # noqa: E402
from delphi.db.repo import init_db  # noqa: E402
from delphi.encyclopedia.service import EncyclopediaService, MapService  # noqa: E402
from delphi.rag.oracle import OracleService  # noqa: E402

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

    # Shareable links, handled once per session:
    #   ?entity=delphi          -> encyclopedia card
    #   ?tab=map                -> map tab
    #   ?entity=delphi&tab=map  -> map centred on the place
    if "url_handled" not in st.session_state:
        st.session_state["url_handled"] = True
        entity = st.query_params.get("entity")
        tab = TAB_SLUGS.get(st.query_params.get("tab", ""))
        if entity and tab == "Карта":
            show_on_map(entity)
        elif entity:
            open_entity(entity)
        elif tab:
            go_to_tab(tab)

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

        # Active tab: `active_tab` is the source of truth. Buttons elsewhere set it and
        # rerun; the radio's own clicks update it through the callback. Syncing the widget
        # key before the radio is created lets code switch tabs programmatically.
        if st.session_state.get("active_tab") not in TABS:
            st.session_state["active_tab"] = TABS[0]
        st.session_state["navigation_radio"] = st.session_state["active_tab"]
        chosen_tab = st.radio(
            "Розділи:",
            TABS,
            key="navigation_radio",
            on_change=lambda: go_to_tab(st.session_state["navigation_radio"]),
        )

        st.divider()
        st.caption("Версія: 0.1.0 (MVP Stage 3: RAG-оракул)")

    # Render selected tab
    if chosen_tab == "Оракул":
        render_oracle_tab(oracle_svc, encyclopedia_svc)
    elif chosen_tab == "Енциклопедія":
        render_encyclopedia_tab(encyclopedia_svc)
    elif chosen_tab == "Карта":
        render_map_tab(map_svc, encyclopedia_svc)


if __name__ == "__main__":
    main()
