import streamlit as st

from app.components.citations import render_citations
from app.components.navigation import open_entity, show_on_map
from delphi.config import settings
from delphi.encyclopedia.service import EncyclopediaService
from delphi.rag.llm import LLMConfigError
from delphi.rag.models import Answer
from delphi.rag.oracle import OracleService

GREETING = (
    "Вітаю тебе, мандрівнику. Я — Піфія, жриця Аполлона. "
    "Запитай мене про богів, героїв та долі античного світу."
)
STYLE_LABELS = {"піфія": "🏛️ Піфія (образно)", "науковий": "📖 Науковий (стисло)"}


def render_oracle_tab(
    oracle_service: OracleService, encyclopedia: EncyclopediaService | None = None
):
    st.header("🔮 Дельфійський оракул")
    st.caption("Відповіді лише на основі античних текстів, з посиланнями на джерела.")

    style = st.selectbox(
        "Стиль відповіді:",
        options=list(STYLE_LABELS),
        format_func=lambda s: STYLE_LABELS.get(s, s),
        key="oracle_style",
    )
    if not oracle_service.retriever.available:
        st.warning("Індекс текстів ще не побудовано: запустіть `delphi ingest`.")

    messages: list[dict] = st.session_state.setdefault(
        "messages", [{"role": "assistant", "text": GREETING}]
    )
    for idx, msg in enumerate(messages):
        with st.chat_message(msg["role"]):
            _render_message(msg, idx, encyclopedia)

    prompt = st.session_state.pop("pending_question", None) or st.chat_input(
        "Поставити запитання Оракулу...", max_chars=settings.max_question_chars
    )
    if not prompt:
        return

    asked = sum(1 for m in messages if m["role"] == "user")
    if asked >= settings.max_questions_per_session:
        st.warning("Ліміт запитань на сесію вичерпано. Оновіть сторінку, щоб почати знову.")
        return
    prompt = prompt[: settings.max_question_chars]

    history = [{"role": m["role"], "text": m["text"]} for m in messages[1:]]
    messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Піфія вдихає священні випари триножника..."):
            prepared = oracle_service.prepare(prompt, history=history, style=style)
        error = None
        try:
            text = st.write_stream(oracle_service.stream(prepared))
        except LLMConfigError as exc:
            text, error = "", str(exc)
        answer = oracle_service.finalize(prepared, str(text or ""), error=error)
        msg = _to_message(answer)
        _render_extras(msg, len(messages), encyclopedia)
    messages.append(msg)


def _to_message(answer: Answer) -> dict:
    return {
        "role": "assistant",
        "text": answer.text,
        "citations": answer.citations,
        "entities": answer.entities,
        "error": answer.error,
    }


def _render_message(msg: dict, idx: int, encyclopedia: EncyclopediaService | None) -> None:
    if msg.get("text"):
        st.markdown(msg["text"])
    _render_extras(msg, idx, encyclopedia)


def _render_extras(msg: dict, idx: int, encyclopedia: EncyclopediaService | None) -> None:
    if msg.get("error"):
        st.warning(
            f"Піфія знайшла джерела, але не може відповісти: {msg['error']} "
            "Нижче — знайдені уривки."
        )
    if msg.get("citations"):
        names = {e.id: e.name_uk for e in encyclopedia.list_entities()} if encyclopedia else None
        render_citations(msg["citations"], key=f"cit_{idx}", names=names)
    if msg.get("entities"):
        _entity_chips(msg["entities"], idx, encyclopedia)


def _entity_chips(entity_ids: list[str], idx: int, encyclopedia: EncyclopediaService | None):
    refs = []
    for eid in entity_ids[:8]:
        card = encyclopedia.get_entity_card(eid) if encyclopedia else None
        refs.append((eid, card.name_uk if card else eid, bool(card and card.place)))
    st.caption("Згадані в відповіді:")
    cols = st.columns(min(len(refs), 4))
    for i, (eid, name, mapped) in enumerate(refs):
        with cols[i % len(cols)]:
            st.button(
                f"📖 {name}",
                key=f"chip_{idx}_{eid}",
                on_click=open_entity,
                args=(eid,),
                width="stretch",
            )
            if mapped:
                st.button(
                    "🗺️ на карті",
                    key=f"chipmap_{idx}_{eid}",
                    on_click=show_on_map,
                    args=(eid,),
                    width="stretch",
                )
