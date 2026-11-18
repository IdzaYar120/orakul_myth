import html

import folium
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from app.components.mini_map import KIND_COLORS, KIND_ICONS, base_map
from app.components.navigation import open_entity
from delphi.encyclopedia.models import MapLayer, MapMarker, MapRoute
from delphi.encyclopedia.service import EncyclopediaService, MapService
from delphi.encyclopedia.vocab import CERTAINTY, PLACE_KINDS

ROUTE_COLORS = {"odysseus_wanderings": "#C0392B", "argonauts_voyage": "#1F6FB2"}
DEFAULT_ROUTE_COLOR = "#7D3C98"
FOCUS_ZOOM = 9


@st.cache_data(show_spinner=False, ttl=600)
def _layer(
    _service: MapService,
    kinds: tuple[str, ...],
    god_id: str | None,
    myth_id: str | None,
    route_ids: tuple[str, ...],
) -> MapLayer:
    return _service.get_map_layer(
        place_kinds=kinds, god_id=god_id, myth_id=myth_id, route_ids=route_ids
    )


def render_map_tab(map_service: MapService, encyclopedia: EncyclopediaService | None = None):
    st.header("🗺️ Античне Середземномор'я")
    st.caption("Святилища, міста, гори й острови міфів, маршрути Одіссея та аргонавтів.")

    options = map_service.filter_options()
    with st.sidebar:
        st.markdown("#### Фільтри карти")
        kinds = st.multiselect(
            "Тип місця",
            options=[k.id for k in options.place_kinds],
            format_func=lambda k: PLACE_KINDS.get(k, k),
            key="map_kinds",
            placeholder="усі типи",
        )
        gods = {g.id: g.label_uk for g in options.gods}
        god_id = st.selectbox(
            "Бог (місця культу)",
            options=[None, *gods],
            format_func=lambda g: "усі" if g is None else gods[g],
            key="map_god",
        )
        myths = {m.id: m.label_uk for m in options.myths}
        myth_id = st.selectbox(
            "Міф",
            options=[None, *myths],
            format_func=lambda m: "усі" if m is None else myths[m],
            key="map_myth",
        )
        routes = {r.id: r.label_uk for r in options.routes}
        route_ids = st.multiselect(
            "Маршрути героїв",
            options=list(routes),
            default=list(routes),
            format_func=lambda r: routes[r],
            key="map_routes",
        )
        cluster = st.toggle("Групувати маркери при віддаленні", value=True, key="map_cluster")

    layer = _layer(map_service, tuple(kinds), god_id, myth_id, tuple(route_ids))

    focus_id = st.session_state.pop("map_focus", None)
    if focus_id:
        st.session_state["map_selected"] = focus_id
    focus = next((mk for mk in layer.markers if mk.entity_id == focus_id), None)
    if focus_id and focus is None:
        # The focused place is hidden by the filters: show it anyway
        everything = map_service.get_map_layer(route_ids=[])
        focus = next((mk for mk in everything.markers if mk.entity_id == focus_id), None)
        if focus:
            layer = layer.model_copy(update={"markers": [*layer.markers, focus]})

    m = base_map(
        location=(focus.lat, focus.lon) if focus else (38.0, 24.0),
        zoom=FOCUS_ZOOM if focus else 6,
    )
    target = MarkerCluster(name="Місця", disable_clustering_at_zoom=8).add_to(m) if cluster else m
    selected = st.session_state.get("map_selected")
    for marker in layer.markers:
        _add_marker(target, marker, highlighted=marker.entity_id == selected)
    for route in layer.routes:
        _add_route(m, route)
    if not focus:
        # Fit everything shown (routes reach from Djerba to Colchis)
        points = [[mk.lat, mk.lon] for mk in layer.markers]
        points += [[s.lat, s.lon] for r in layer.routes for s in r.stops]
        if len(points) > 1:
            m.fit_bounds(points, padding=(20, 20), max_zoom=FOCUS_ZOOM)

    col_map, col_side = st.columns([3, 1])
    with col_map:
        out = st_folium(
            m,
            key="main_map",
            height=600,
            use_container_width=True,
            returned_objects=["last_object_clicked"],
            layer_control=folium.LayerControl(collapsed=True),
        )
        st.caption(f"Місць на карті: {len(layer.markers)}")
        for route in layer.routes:
            if route.is_speculative:
                st.caption(
                    f"⚠ **{route.title_uk}**: традиційні ототожнення, не факт. "
                    "Пунктир — непевна локалізація зупинки."
                )

    # Marker click -> nearest place -> card on the right
    clicked = (out or {}).get("last_object_clicked")
    if clicked and clicked != st.session_state.get("map_last_click"):
        st.session_state["map_last_click"] = clicked
        nearest = map_service.nearest_place(clicked["lat"], clicked["lng"])
        if nearest:
            st.session_state["map_selected"] = nearest

    with col_side:
        selected = st.session_state.get("map_selected")
        if selected and encyclopedia is not None:
            _side_card(encyclopedia, selected)
        else:
            st.info("Клацніть маркер, щоб побачити картку місця.")
        _legend(layer)


def _add_marker(target, marker: MapMarker, highlighted: bool = False) -> None:
    kind = PLACE_KINDS.get(marker.place_kind, marker.place_kind)
    summary = (marker.summary_uk or "").split(". ")[0].rstrip(".")
    patrons = ", ".join(p.name_uk for p in marker.patrons)
    popup = f"<b>{html.escape(marker.name_uk)}</b> <i>({html.escape(kind.lower())})</i>"
    if summary:
        popup += f"<br>{html.escape(summary)}."
    if patrons:
        popup += f"<br><b>Покровителі:</b> {html.escape(patrons)}"
    if marker.certainty != "high":
        popup += f"<br><i>{html.escape(CERTAINTY.get(marker.certainty, marker.certainty))}</i>"
    folium.Marker(
        location=[marker.lat, marker.lon],
        popup=folium.Popup(popup, max_width=280),
        tooltip=f"{marker.name_uk} · {kind.lower()}",
        icon=folium.Icon(
            color="red" if highlighted else KIND_COLORS.get(marker.place_kind, "blue"),
            icon=KIND_ICONS.get(marker.place_kind, "info"),
            prefix="fa",
        ),
    ).add_to(target)


def _add_route(m: folium.Map, route: MapRoute) -> None:
    color = ROUTE_COLORS.get(route.id, DEFAULT_ROUTE_COLOR)
    group = folium.FeatureGroup(name=route.title_uk).add_to(m)
    stops = route.stops
    for a, b in zip(stops, stops[1:], strict=False):
        uncertain = a.certainty != "high" or b.certainty != "high"
        folium.PolyLine(
            locations=[[a.lat, a.lon], [b.lat, b.lon]],
            color=color,
            weight=3,
            opacity=0.8,
            dash_array="6, 8" if uncertain else None,
            tooltip=f"{route.title_uk}: {a.title} → {b.title}",
        ).add_to(group)
    for stop in stops:
        label = html.escape(f"{stop.stop_number}. {stop.title}")
        details = html.escape(stop.description or "")
        source = html.escape(stop.source_ref or "")
        certainty = html.escape(CERTAINTY.get(stop.certainty, stop.certainty))
        badge = (
            f'<div style="background:{color};color:#fff;border-radius:50%;width:22px;'
            "height:22px;line-height:22px;text-align:center;font:bold 12px sans-serif;"
            f'border:2px solid #fff">{stop.stop_number}</div>'
        )
        folium.Marker(
            location=[stop.lat, stop.lon],
            icon=folium.DivIcon(html=badge, icon_size=(22, 22), icon_anchor=(11, 11)),
            tooltip=label,
            popup=folium.Popup(
                f"<b>{label}</b><br>{details}<br><i>{source}</i> · {certainty}", max_width=280
            ),
        ).add_to(group)


def _side_card(service: EncyclopediaService, entity_id: str) -> None:
    card = service.get_entity_card(entity_id)
    if card is None:
        return
    st.markdown(f"#### {card.name_uk}")
    if card.place:
        st.caption(PLACE_KINDS.get(card.place.place_kind, card.place.place_kind))
    if card.summary_uk:
        st.write(card.summary_uk)
    for group in card.other_relations:
        st.markdown(f"**{group.label_uk}:** " + ", ".join(i.entity.name_uk for i in group.items))
    if card.myths:
        st.markdown("**Міфи:** " + "; ".join(m.title_uk for m in card.myths))
    st.button(
        "📖 Відкрити картку",
        key=f"map_open_{card.id}",
        on_click=open_entity,
        args=(card.id,),
        width="stretch",
    )


def _legend(layer: MapLayer) -> None:
    with st.expander("Легенда"):
        for kind, label in PLACE_KINDS.items():
            st.markdown(f":{_streamlit_color(KIND_COLORS.get(kind, 'blue'))}[●] {label}")
        for route in layer.routes:
            color = ROUTE_COLORS.get(route.id, DEFAULT_ROUTE_COLOR)
            st.markdown(
                f"<span style='color:{color}'>━━</span> {html.escape(route.title_uk)}",
                unsafe_allow_html=True,
            )
    if layer.off_map:
        with st.expander(f"Поза картою ({len(layer.off_map)})"):
            st.caption("Міфічні місця без реальної локалізації.")
            for ref in layer.off_map:
                st.button(
                    ref.name_uk,
                    key=f"offmap_{ref.id}",
                    on_click=open_entity,
                    args=(ref.id,),
                    width="stretch",
                )


def _streamlit_color(folium_color: str) -> str:
    return {
        "purple": "violet",
        "blue": "blue",
        "green": "green",
        "orange": "orange",
        "cadetblue": "blue",
        "darkred": "red",
    }.get(folium_color, "gray")
