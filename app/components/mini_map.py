import folium
from streamlit_folium import st_folium

from delphi.encyclopedia.models import MapMarker
from delphi.encyclopedia.vocab import PLACE_KINDS

# Basemaps without an API key. CARTO Positron (the architecture doc's choice) now
# requires a key and serves "API KEY REQUIRED" watermarked tiles without one.
ESRI_LIGHT_GRAY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
    "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
)
ESRI_ATTRIBUTION = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
OSM_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
PLEIADES_ATTRIBUTION = 'Places: <a href="https://pleiades.stoa.org/">Pleiades</a> (CC BY)'

KIND_COLORS = {
    "sanctuary": "purple",
    "city": "blue",
    "mountain": "green",
    "island": "orange",
    "river": "cadetblue",
    "region": "darkred",
}


def base_map(
    location: tuple[float, float] = (38.0, 24.0), zoom: int = 6, layer_control: bool = False
) -> folium.Map:
    m = folium.Map(location=list(location), zoom_start=zoom, tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=ESRI_LIGHT_GRAY_URL,
        attr=f"{ESRI_ATTRIBUTION} | {PLEIADES_ATTRIBUTION}",
        name="Світла (Esri Light Gray)",
        max_zoom=16,
    ).add_to(m)
    folium.TileLayer(
        tiles=OSM_URL,
        attr=f"{OSM_ATTRIBUTION} | {PLEIADES_ATTRIBUTION}",
        name="OpenStreetMap",
        max_zoom=19,
        show=False,
    ).add_to(m)
    if layer_control:
        folium.LayerControl(collapsed=True).add_to(m)
    return m


def render_mini_map(markers: list[MapMarker], key: str, height: int = 280) -> None:
    if not markers:
        return
    m = base_map(location=(markers[0].lat, markers[0].lon), zoom=7)
    for mk in markers:
        kind = PLACE_KINDS.get(mk.place_kind, mk.place_kind)
        label = f"{mk.name_uk} — {mk.relation_label}" if mk.relation_label else mk.name_uk
        folium.Marker(
            location=[mk.lat, mk.lon],
            tooltip=f"{label} ({kind.lower()})",
            icon=folium.Icon(color=KIND_COLORS.get(mk.place_kind, "blue"), icon="info-sign"),
        ).add_to(m)
    if len(markers) > 1:
        m.fit_bounds([[mk.lat, mk.lon] for mk in markers], padding=(30, 30), max_zoom=8)
    st_folium(m, key=key, height=height, use_container_width=True, returned_objects=[])
