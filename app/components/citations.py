import streamlit as st

from delphi.rag.models import Citation


def render_citations(citations: list[Citation], key: str) -> None:
    """Sources under an answer: cited ones first; the English passage in an expander."""
    if not citations:
        return
    cited = [c for c in citations if c.cited]
    other = [c for c in citations if not c.cited]
    st.markdown("##### 📜 Першоджерела")
    for c in cited or citations:
        _citation(c)
    if cited and other:
        with st.expander(f"Інші знайдені уривки ({len(other)})"):
            for c in other:
                _citation(c, nested=True)
    st.caption(
        "Переклади початку XX ст. (суспільне надбання); TEI-розмітка — Perseus Digital Library, "
        "CC BY-SA 4.0."
    )
    _ = key


def _citation(c: Citation, nested: bool = False) -> None:
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
