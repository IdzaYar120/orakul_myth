import streamlit as st

from delphi.rag.models import Citation


def render_citations(citations: list[Citation]):
    """Відображає розгортаний список цитат-джерел під відповіддю оракула."""
    if not citations:
        return

    st.markdown("##### 📜 Першоджерела")
    for c in citations:
        with st.expander(f"[{c.num}] {c.author} — «{c.work}» ({c.ref})"):
            st.markdown(f"> *{c.text_en}*")
            if c.source_url:
                st.caption(f"[Відкрити на Perseus/Gutenberg]({c.source_url})")
