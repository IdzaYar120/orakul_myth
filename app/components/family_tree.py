import json

import streamlit as st

from delphi.encyclopedia.models import EntityCard, RelatedEntity

PER_ROW = 8  # children per row
COL_W = 150  # horizontal distance between nodes
ROW_H = 110  # vertical distance between rows

COLORS = {
    "parent": "#7FA7D9",
    "self": "#E0B84F",
    "spouse": "#E59BB5",
    "sibling": "#C9CDD3",
    "child": "#7FC8A9",
}


def _row_x(count: int, offset: float = 0.0) -> list[float]:
    """x positions of `count` nodes centred around `offset`."""
    return [offset + (i - (count - 1) / 2) * COL_W for i in range(count)]


@st.cache_data(show_spinner=False)
def _tree_html(card_json: str) -> tuple[str, int]:
    """Lay the tree out explicitly (parents / self row / children grid): vis.js hierarchical
    layout stretches large families like Zeus's into an unreadable single line."""
    from pyvis.network import Network

    card = EntityCard.model_validate_json(card_json)
    lin = card.lineage
    parent_ids = {p.entity.id for p in lin.parents}
    spouses = [s for s in lin.spouses if s.entity.id not in parent_ids]
    siblings = [s for s in lin.siblings if s.entity.id not in parent_ids]
    children = lin.children

    child_rows = max(1, -(-len(children) // PER_ROW)) if children else 0
    height = ROW_H * (1 + int(bool(lin.parents)) + child_rows) + 60
    net = Network(height=f"{height}px", width="100%", directed=True, bgcolor="#ffffff")

    def node(item_id: str, label: str, role: str, x: float, y: float, title: str) -> None:
        net.add_node(
            item_id,
            label=label,
            title=title or label,
            color=COLORS[role],
            shape="box",
            x=x,
            y=y,
            physics=False,
            font={"size": 14},
            margin=8,
        )

    def tip(item: RelatedEntity) -> str:
        return f"{item.entity.name_uk}: " + "; ".join(item.source_refs)

    y = 0.0
    if lin.parents:
        for x, p in zip(_row_x(len(lin.parents)), lin.parents, strict=True):
            node(p.entity.id, p.entity.name_uk, "parent", x, y, p.entity.summary_uk or "")
        y += ROW_H

    # Middle row: siblings on the left, the entity, spouses on the right
    middle = [*siblings, None, *spouses]
    self_index = len(siblings)
    xs = _row_x(len(middle), offset=0)
    shift = -xs[self_index]  # keep the entity centred under its parents
    for i, item in enumerate(middle):
        x = xs[i] + shift
        if item is None:
            node(card.id, card.name_uk, "self", x, y, card.summary_uk or "")
        elif i < self_index:
            node(item.entity.id, item.entity.name_uk, "sibling", x, y, tip(item))
        else:
            node(item.entity.id, item.entity.name_uk, "spouse", x, y, tip(item))
    for p in lin.parents:
        net.add_edge(p.entity.id, card.id, title=tip(p), dashes=not p.verified, width=2)
        for s in siblings:
            net.add_edge(p.entity.id, s.entity.id, color="#D5D8DD", arrows="")
    for s in spouses:
        net.add_edge(
            card.id,
            s.entity.id,
            title=tip(s),
            dashes=not s.verified,
            arrows="",
            color="#E59BB5",
            width=2,
        )

    y += ROW_H
    for row in range(child_rows):
        chunk = children[row * PER_ROW : (row + 1) * PER_ROW]
        for x, c in zip(_row_x(len(chunk)), chunk, strict=True):
            node(c.entity.id, c.entity.name_uk, "child", x, y + row * ROW_H, tip(c))
            net.add_edge(card.id, c.entity.id, title=tip(c), dashes=not c.verified)

    net.set_options(
        json.dumps(
            {
                "physics": {"enabled": False},
                "interaction": {"hover": True, "dragNodes": True, "zoomView": True},
                "edges": {
                    "smooth": {"type": "cubicBezier", "forceDirection": "vertical"},
                    "color": {"color": "#9AA3AF"},
                },
            }
        )
    )
    html: str = net.generate_html()
    return html, height


def render_family_tree(card: EntityCard) -> None:
    """Mini lineage graph: parents above, siblings | entity | spouses, children below.

    Dashed edges are relations not yet checked against an ancient source.
    """
    if card.lineage.is_empty:
        return
    try:
        html, height = _tree_html(card.model_dump_json())
        st.iframe(html, height=height + 20)
        st.caption(
            "Пунктир — зв'язок ще не звірено з першоджерелом. "
            "Наведіть на вузол чи лінію, щоб побачити джерело."
        )
    except Exception:  # pragma: no cover - graph is a nice-to-have, lists below remain
        st.caption("Не вдалося побудувати граф родоводу.")
