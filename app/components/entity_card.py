import streamlit as st

from app.components.family_tree import render_family_tree
from app.components.mini_map import render_mini_map
from app.components.navigation import ask_oracle, open_entity
from delphi.encyclopedia.models import EntityCard, RelatedEntity
from delphi.encyclopedia.vocab import (
    CERTAINTY,
    ENTITY_TYPES,
    MYTH_CYCLES,
    MYTH_ROLES,
    PLACE_KINDS,
)

UNVERIFIED_MARK = "⚠"
UNVERIFIED_HELP = (
    f"{UNVERIFIED_MARK} — зв'язок узято з Wikidata або внесено вручну; "
    "ще не звірено з античним першоджерелом."
)


def render_entity_card(card: EntityCard) -> None:
    """Entity card: names, description, lineage with sources, places, myths, passages."""
    st.subheader(card.name_uk)
    names = [f"грец./англ.: {card.name_en}"]
    if card.name_lat and card.name_lat != card.name_en:
        names.append(f"рим./лат.: {card.name_lat}")
    names.append(ENTITY_TYPES.get(card.type, card.type))
    if card.place:
        names.append(PLACE_KINDS.get(card.place.place_kind, card.place.place_kind))
    st.caption(" · ".join(names))

    left, right = st.columns([3, 2])
    with left:
        if card.summary_uk:
            st.markdown(card.summary_uk)
        if card.domain:
            st.markdown(f"**Сфера:** {card.domain}")
        if card.symbols:
            st.markdown(f"**Символи й атрибути:** {', '.join(card.symbols)}")
        if card.cycles:
            st.markdown("**Цикли міфів:** " + ", ".join(MYTH_CYCLES.get(c, c) for c in card.cycles))
        if card.type == "place" and card.place is None:
            st.info(f"Місце без точної локалізації: {CERTAINTY['none']}.")
        elif card.place and card.place.certainty != "high":
            st.caption(f"Локалізація: {CERTAINTY.get(card.place.certainty, card.place.certainty)}")
        _links(card)
        if len(card.aliases) > 1:
            with st.expander("Інші назви"):
                st.write(", ".join(card.aliases))
    with right:
        if card.places:
            render_mini_map(card.places, key=f"mini_{card.id}")

    if not card.lineage.is_empty:
        st.markdown("#### 🌿 Родовід")
        render_family_tree(card)
        _lineage_lists(card)

    for group in card.other_relations:
        _chips(group.label_uk, group.items, key=f"rel_{card.id}_{group.rel}_{group.direction}")

    if card.myths:
        st.markdown("#### 🏛️ Міфи")
        for myth in card.myths:
            role = MYTH_ROLES.get(myth.role, myth.role)
            cycle = MYTH_CYCLES.get(myth.cycle, myth.cycle)
            with st.expander(f"{myth.title_uk} · {cycle} · {role}"):
                st.write(myth.summary_uk)
                if myth.participants:
                    names = {p.id: p.name_uk for p in myth.participants}
                    st.pills(
                        "Учасники",
                        options=list(names),
                        format_func=lambda eid, names=names: names.get(eid, eid),
                        key=f"myth_{card.id}_{myth.id}",
                        on_change=_navigate,
                        args=(f"myth_{card.id}_{myth.id}",),
                    )

    st.markdown("#### 📜 Уривки з джерел")
    if card.passages:
        for p in card.passages:
            with st.expander(f"{p.author}, {p.work} {p.ref}"):
                st.markdown(f"> {p.text}")
    else:
        st.caption("Уривки з античних текстів з'являться після інгесту корпусу (етап 3).")

    st.divider()
    pronoun = "неї" if card.type == "place" else "нього"
    st.button(
        f"🔮 Запитати оракула про {card.name_uk}",
        key=f"ask_oracle_{card.id}",
        on_click=ask_oracle,
        args=(f"Розкажи про {card.name_uk}: хто це і які міфи з {pronoun} пов'язані?",),
    )
    st.caption(f"Посилання на картку: `?entity={card.id}`")


def _links(card: EntityCard) -> None:
    links = []
    if card.wikidata_id:
        links.append(
            f"[Wikidata {card.wikidata_id}](https://www.wikidata.org/wiki/{card.wikidata_id})"
        )
    if card.place and card.place.pleiades_id:
        pid = card.place.pleiades_id
        links.append(f"[Pleiades {pid}](https://pleiades.stoa.org/places/{pid})")
    if links:
        st.caption(" · ".join(links))


def _lineage_lists(card: EntityCard) -> None:
    lin = card.lineage
    _chips("Батьки", lin.parents, key=f"lin_{card.id}_parents")
    _chips("Подружжя", lin.spouses, key=f"lin_{card.id}_spouses")
    _chips("Діти", lin.children, key=f"lin_{card.id}_children")
    _chips("Брати й сестри", lin.siblings, key=f"lin_{card.id}_siblings")
    if lin.half_siblings:
        total = sum(len(g.items) for g in lin.half_siblings)
        with st.expander(f"Зведені брати й сестри ({total})"):
            for group in lin.half_siblings:
                _chips(
                    f"через {group.via.name_uk}",
                    group.items,
                    key=f"lin_{card.id}_half_{group.via.id}",
                    show_sources=False,
                )

    rows = [
        (label, item)
        for label, items in (
            ("батьки", lin.parents),
            ("подружжя", lin.spouses),
            ("діти", lin.children),
        )
        for item in items
    ]
    if rows:
        with st.expander("Джерела зв'язків"):
            st.caption(UNVERIFIED_HELP)
            st.markdown(
                "\n".join(
                    f"- {label}: **{item.entity.name_uk}** — "
                    + "; ".join(_ref_label(r) for r in item.source_refs)
                    for label, item in rows
                )
            )


def _ref_label(ref: str) -> str:
    if ref == "Wikidata":
        return f"{UNVERIFIED_MARK} Wikidata"
    if ref == "manual":
        return f"{UNVERIFIED_MARK} без джерела"
    return f"`{ref}`"


def _chips(label: str, items: list[RelatedEntity], key: str, show_sources: bool = True) -> None:
    """Clickable entity chips; ⚠ marks relations not yet checked against a primary source."""
    if not items:
        return

    def fmt(eid: str) -> str:
        item = next(i for i in items if i.entity.id == eid)
        name = item.entity.name_uk
        if show_sources:
            refs = ", ".join(r for r in item.source_refs if r not in ("Wikidata", "manual"))
            if refs:
                name += f" ({refs})"
            elif not item.verified:
                name += f" {UNVERIFIED_MARK}"
        return name

    st.pills(
        label,
        options=[i.entity.id for i in items],
        format_func=fmt,
        key=key,
        on_change=_navigate,
        args=(key,),
    )


def _navigate(key: str) -> None:
    """Pills callback: open the chosen entity and reset the pill selection."""
    entity_id = st.session_state.get(key)
    st.session_state[key] = None
    if entity_id:
        open_entity(entity_id)
