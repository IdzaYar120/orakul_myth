import streamlit as st

from app.components.navigation import open_entity
from delphi.rag.models import Citation

MAX_PASSAGE_ENTITIES = 6


def render_citations(
    citations: list[Citation], key: str, names: dict[str, str] | None = None
) -> None:
    """Sources under an answer: cited ones first; the English passage in an expander, with
    buttons to the cards of the entities named in it (`names`: entity id -> Ukrainian name)."""
    if not citations:
        return
    cited = [c for c in citations if c.cited]
    other = [c for c in citations if not c.cited]
    st.markdown("##### 📜 Першоджерела")
    for c in cited or citations:
        _citation(c, key=key, names=names or {})
    if cited and other:
        with st.expander(f"Інші знайдені уривки ({len(other)})"):
            for c in other:
                _citation(c, nested=True)
    st.caption(
        "Переклади початку XX ст. (суспільне надбання); TEI-розмітка — Perseus Digital Library, "
        "CC BY-SA 4.0."
    )
    _ = key


def _citation(
    c: Citation, nested: bool = False, key: str = "", names: dict[str, str] | None = None
) -> None:
    title = f"[{c.num}] {c.ref} · {c.translator or c.author}"
    if nested:
        st.markdown(f"**{title}**")
        st.markdown(f"> {c.text_en}")
        return
    with st.expander(title):
        st.markdown(f"> {c.text_en}")
        if c.notes:
            st.caption("Примітки перекладача: " + " · ".join(n[:300] for n in c.notes[:3]))
        if c.source_url:
            st.caption(f"[Текст на Perseus]({c.source_url})")
        named = [e for e in c.entity_ids if names and e in names][:MAX_PASSAGE_ENTITIES]
        if named:
            st.caption("Згадані в уривку:")
            cols = st.columns(min(len(named), 3))
            for i, eid in enumerate(named):
                with cols[i % len(cols)]:
                    st.button(
                        f"📖 {(names or {})[eid]}",
                        key=f"{key}_{c.num}_{eid}",
                        on_click=open_entity,
                        args=(eid,),
                        width="stretch",
                    )
