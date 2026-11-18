import folium
import streamlit as st
from streamlit_folium import st_folium

from delphi.encyclopedia.service import MapService


def render_map_tab(map_service: MapService):
    st.header("🗺️ Античне Середземномор'я")
    st.caption("Інтерактивна карта святилищ, міст, гір та маршрутів античних героїв.")

    layer = map_service.get_map_layer()

    # Створюємо Folium карту з центром в Егейському морі
    m = folium.Map(
        location=[38.5, 24.0],
        zoom_start=6,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # Кольори для типів місць
    kind_colors = {
        "sanctuary": "purple",
        "city": "blue",
        "mountain": "green",
        "island": "orange",
        "river": "cadetblue",
        "region": "darkred",
    }

    # Додаємо маркери
    for marker in layer.markers:
        color = kind_colors.get(marker.place_kind, "blue")
        popup_html = f"""
        <b>{marker.name_uk}</b> ({marker.place_kind})<br>
        <p>{marker.summary_uk or ""}</p>
        """
        folium.Marker(
            location=[marker.lat, marker.lon],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=f"{marker.name_uk} ({marker.place_kind})",
            icon=folium.Icon(color=color, icon="info-sign"),
        ).add_to(m)

    # Додаємо маршрути
    for r in layer.routes:
        if len(r.stops) >= 2:
            coords = [[s.lat, s.lon] for s in r.stops]
            folium.PolyLine(
                locations=coords,
                color="red",
                weight=3,
                opacity=0.7,
                tooltip=f"{r.title_uk} (традиційна реконструкція)",
                dash_array="5, 10",
            ).add_to(m)

    col1, col2 = st.columns([3, 1])
    with col1:
        map_output = st_folium(m, width="100%", height=550)

    with col2:
        st.markdown("##### 📌 Легенда місць")
        for k, col in kind_colors.items():
            st.markdown(f"- **{k}**: :{col}[●]")

        if layer.routes:
            st.markdown("##### 🚢 Маршрути")
            for r in layer.routes:
                st.markdown(f"- **{r.title_uk}**")
                st.caption(r.description_uk or "")

        # Якщо клікнули на маркер
        if map_output and map_output.get("last_object_clicked"):
            st.info("Вибрано об'єкт на карті.")
