import streamlit as st
import streamlit.components.v1 as components

from delphi.encyclopedia.models import EntityRelationItem


def render_family_tree(entity_name: str, relations: list[EntityRelationItem], height: int = 250):
    """Renders mini lineage graph (parents, children, spouses) using pyvis HTML component."""
    if not relations:
        st.info("Відомостей про родовід у джерелах наразі немає.")
        return

    try:
        from pyvis.network import Network

        net = Network(height=f"{height}px", width="100%", bgcolor="#f8f9fa", font_color="#212529")
        net.add_node(entity_name, label=entity_name, color="#4A90E2", size=25)

        for rel in relations:
            label_text = rel.rel.replace("_", " ")
            net.add_node(rel.target_name_uk, label=rel.target_name_uk, color="#50E3C2", size=20)
            net.add_edge(
                entity_name,
                rel.target_name_uk,
                title=f"{label_text} ({rel.source_ref})",
                label=label_text,
            )

        net.set_options(
            """
        var options = {
          "physics": {
            "barnesHut": {
              "springLength": 90
            }
          }
        }
        """
        )
        html_str = net.generate_html()
        components.html(html_str, height=height)
    except Exception:
        # Fallback if pyvis fails to generate HTML
        st.markdown("**Зв'язки родоводу:**")
        for r in relations:
            st.markdown(f"- *{r.rel}*: **{r.target_name_uk}** `[{r.source_ref}]`")
