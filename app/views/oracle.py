import streamlit as st

from app.components.citations import render_citations
from app.components.navigation import open_entity
from delphi.rag.oracle import OracleService


def render_oracle_tab(oracle_service: OracleService):
    st.header("🔮 Дельфійський оракул")
    st.caption("ШІ-чат, що відповідає на основі античних джерел із точними посиланнями.")

    # Style configuration
    col1, col2 = st.columns([1, 3])
    with col1:
        style = st.selectbox(
            "Стиль відповіді:",
            options=["піфія", "науковий"],
            format_func=lambda s: "🏛️ Піфія (образно)" if s == "піфія" else "📖 Науковий (стисло)",
        )

    # Initialize message history in st.session_state
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {
                "role": "assistant",
                "text": (
                    "Вітаю тебе, мандрівнику. Я — Піфія, жриця Аполлона. "
                    "Запитай мене про богів, героїв та долі античного світу."
                ),
                "citations": [],
                "entities": [],
            }
        ]

    # Render message history
    for msg_idx, msg in enumerate(st.session_state["messages"]):
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg.get("citations"):
                render_citations(msg["citations"])
            if msg.get("entities"):
                cols = st.columns(len(msg["entities"]) + 1)
                for i, eid in enumerate(msg["entities"]):
                    with cols[i]:
                        st.button(
                            f"🔍 {eid}",
                            key=f"chip_{msg_idx}_{eid}_{i}",
                            on_click=open_entity,
                            args=(eid,),
                        )

    # Check for pending question (e.g. from encyclopedia)
    prompt = None
    if st.session_state.get("pending_question"):
        prompt = st.session_state.pop("pending_question")
    else:
        prompt = st.chat_input("Поставити запитання Оракулу...")

    if prompt:
        # Append user query
        st.session_state["messages"].append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Піфія вдихає священні випари триножника..."):
                answer = oracle_service.ask(prompt, style=style)
                st.markdown(answer.text)
                if answer.citations:
                    render_citations(answer.citations)

                if answer.entities:
                    st.caption("Пов'язані сутності:")
                    c_cols = st.columns(len(answer.entities) + 2)
                    for i, eid in enumerate(answer.entities):
                        with c_cols[i]:
                            st.button(
                                f"Картка {eid}",
                                key=f"ans_chip_{eid}_{i}",
                                on_click=open_entity,
                                args=(eid,),
                            )

        st.session_state["messages"].append(
            {
                "role": "assistant",
                "text": answer.text,
                "citations": answer.citations,
                "entities": answer.entities,
            }
        )
