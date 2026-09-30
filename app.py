import streamlit as st
import geopandas as gpd
import folium
from folium import FeatureGroup
from folium.plugins import Fullscreen, MousePosition, MiniMap
from streamlit_folium import st_folium
from branca.element import MacroElement, Template
from pathlib import Path
import pandas as pd
import html
import hashlib

# ============================================================
# CONFIGURACIÓN
# ============================================================
st.set_page_config(
    page_title="Visor Hidrológico Sudamérica",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Estructura esperada:
# data/
# ├── cuenca/
# ├── rio/
# ├── estaciones/
# └── limite/
#
# El programa busca TODOS los .shp dentro de esas carpetas,
# incluyendo subcarpetas.

GROUPS = {
    "cuenca": {
        "label": "Cuencas",
        "folder": DATA_DIR / "cuenca",
        "geometry": "polygon",
        "color": "#2E86AB",
    },
    "rio": {
        "label": "Ríos",
        "folder": DATA_DIR / "rio",
        "geometry": "line",
        "color": "#1677FF",
    },
    "estaciones": {
        "label": "Estaciones / Puntos",
        "folder": DATA_DIR / "estaciones",
        "geometry": "point",
        "color": "#E63946",
    },
    "limite": {
        "label": "Límite / Sudamérica",
        "folder": DATA_DIR / "limite",
        "geometry": "polygon",
        "color": "#555555",
    },
}

PALETTE = [
    "#2563EB", "#059669", "#7C3AED", "#DC2626", "#EA580C",
    "#0891B2", "#CA8A04", "#DB2777", "#4F46E5", "#65A30D",
    "#9333EA", "#0F766E", "#B45309", "#BE123C", "#0369A1",
]

# ============================================================
# UTILIDADES
# ============================================================
def nice_name(path: Path) -> str:
    """Convierte nombre de archivo a un nombre legible."""
    return path.stem.replace("_", " ").replace("-", " ").title()


def find_shapefiles(folder: Path):
    """Busca shapefiles recursivamente."""
    if not folder.exists():
        return []
    return sorted(folder.rglob("*.shp"), key=lambda p: p.name.lower())


@st.cache_data(show_spinner=False)
def discover_files():
    result = {}
    for key, cfg in GROUPS.items():
        result[key] = find_shapefiles(cfg["folder"])
    return result


@st.cache_data(show_spinner=True, ttl=3600)
def load_layer(path_str: str):
    """
    Lee un shapefile y lo convierte a WGS84.
    Devuelve GeoDataFrame.
    """
    gdf = gpd.read_file(path_str)

    if gdf.empty:
        return gdf

    if gdf.crs is None:
        # Se intenta mostrar, pero no se inventa una proyección.
        # La mayoría de los shapefiles suministrados deben tener .prj.
        st.warning(
            f"El archivo {Path(path_str).name} no tiene CRS (.prj). "
            "Se mantendrá su sistema de coordenadas original."
        )
    else:
        gdf = gdf.to_crs(epsg=4326)

    # Eliminar geometrías vacías o nulas
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    return gdf


def safe_text(value):
    if pd.isna(value):
        return ""
    return html.escape(str(value))


def popup_html(row):
    """Genera un popup profesional con los atributos del elemento."""
    attrs = []
    for col in row.index:
        if col == "geometry":
            continue
        value = row[col]
        if pd.isna(value):
            continue
        attrs.append(
            f"""
            <tr>
                <td style="font-weight:600;padding:4px 8px;
                           border-bottom:1px solid #eee;">
                    {safe_text(col)}
                </td>
                <td style="padding:4px 8px;border-bottom:1px solid #eee;">
                    {safe_text(value)}
                </td>
            </tr>
            """
        )

    if not attrs:
        attrs.append(
            '<tr><td colspan="2" style="padding:8px;">Sin atributos disponibles</td></tr>'
        )

    return f"""
    <div style="font-family:Arial,sans-serif;min-width:250px;max-width:420px;">
        <div style="font-size:15px;font-weight:700;margin-bottom:8px;
                    color:#12344D;">
            Información del elemento
        </div>
        <table style="border-collapse:collapse;width:100%;font-size:12px;">
            {''.join(attrs)}
        </table>
    </div>
    """


def add_legend(m, selected_layers):
    """Leyenda HTML fija en el mapa."""
    items = []

    for item in selected_layers:
        color = item["color"]
        geometry = item["geometry"]
        name = item["name"]

        if geometry == "point":
            symbol = (
                f'<span style="display:inline-block;width:11px;height:11px;'
                f'border-radius:50%;background:{color};border:2px solid white;'
                f'box-shadow:0 0 0 1px {color};margin-right:7px;"></span>'
            )
        elif geometry == "line":
            symbol = (
                f'<span style="display:inline-block;width:23px;height:4px;'
                f'background:{color};margin-right:7px;vertical-align:middle;"></span>'
            )
        else:
            symbol = (
                f'<span style="display:inline-block;width:15px;height:15px;'
                f'background:{color}33;border:2px solid {color};'
                f'margin-right:7px;vertical-align:middle;"></span>'
            )

        items.append(f"<div style='margin:5px 0;'>{symbol}{html.escape(name)}</div>")

    if not items:
        items.append(
            "<div style='color:#666;font-size:12px;'>No hay capas seleccionadas</div>"
        )

    legend = f"""
    <div style="
        position: fixed;
        bottom: 25px;
        left: 25px;
        z-index: 9999;
        background: rgba(255,255,255,0.96);
        padding: 13px 16px;
        border-radius: 10px;
        box-shadow: 0 2px 12px rgba(0,0,0,.22);
        min-width: 210px;
        max-width: 330px;
        font-family: Arial, sans-serif;
        font-size: 12px;
    ">
        <div style="font-size:14px;font-weight:700;color:#12344D;
                    border-bottom:1px solid #ddd;padding-bottom:7px;margin-bottom:7px;">
            LEYENDA
        </div>
        {''.join(items)}
    </div>
    """

    macro = MacroElement()
    macro._template = Template(f"""
    {{% macro html(this, kwargs) %}}
    {legend}
    {{% endmacro %}}
    """)
    m.get_root().add_child(macro)


def color_for_layer(index, group_key):
    if group_key == "limite":
        return "#374151"
    if group_key == "rio":
        return "#1677FF"
    if group_key == "estaciones":
        return "#E63946"
    return PALETTE[index % len(PALETTE)]


def add_geodata_layer(
    m,
    gdf,
    layer_name,
    geometry_type,
    color,
    opacity,
    line_width,
    point_radius,
):
    """Agrega una capa GeoDataFrame a Folium."""
    fg = FeatureGroup(name=layer_name, show=True)

    if gdf.empty:
        return

    # Para mejorar rendimiento en mapas web, se conserva la geometría,
    # pero se evita enviar columnas innecesarias al tooltip.
    tooltip_cols = [
        c for c in gdf.columns
        if c != "geometry"
    ][:8]

    if geometry_type == "point":
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue

            # Soporta Point y MultiPoint
            points = []
            if geom.geom_type == "Point":
                points = [geom]
            elif geom.geom_type == "MultiPoint":
                points = list(geom.geoms)

            for point in points:
                popup = folium.Popup(
                    popup_html(row),
                    max_width=450
                )

                folium.CircleMarker(
                    location=[point.y, point.x],
                    radius=point_radius,
                    color=color,
                    weight=2,
                    fill=True,
                    fill_color=color,
                    fill_opacity=opacity,
                    popup=popup,
                    tooltip=layer_name,
                ).add_to(fg)

    else:
        style = {
            "color": color,
            "weight": line_width if geometry_type == "line" else 1.8,
            "opacity": opacity,
            "fillColor": color,
            "fillOpacity": opacity * 0.20 if geometry_type == "polygon" else 0,
        }

        folium.GeoJson(
            gdf.to_json(),
            name=layer_name,
            style_function=lambda feature, s=style: s,
            highlight_function=lambda feature: {
                "weight": max(s["weight"] + 1.5, 3),
                "opacity": 1,
                "fillOpacity": min(s["fillOpacity"] + 0.10, 0.45),
            },
            popup=folium.GeoJsonPopup(
                fields=tooltip_cols,
                aliases=tooltip_cols,
                localize=True,
                labels=True,
                sticky=False,
                max_width=450,
            ) if tooltip_cols else None,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_cols[:3],
                aliases=tooltip_cols[:3],
                sticky=False,
            ) if tooltip_cols else None,
        ).add_to(fg)

    fg.add_to(m)


def calculate_center(all_gdfs):
    """Calcula centro del mapa usando las capas disponibles."""
    bounds = []

    for gdf in all_gdfs:
        if gdf is None or gdf.empty:
            continue
        try:
            b = gdf.total_bounds
            if all(pd.notna(b)):
                bounds.append(b)
        except Exception:
            pass

    if not bounds:
        return [-9.2, -75.0], 4

    minx = min(b[0] for b in bounds)
    miny = min(b[1] for b in bounds)
    maxx = max(b[2] for b in bounds)
    maxy = max(b[3] for b in bounds)

    center = [(miny + maxy) / 2, (minx + maxx) / 2]

    # Zoom inicial razonable para Sudamérica.
    width = maxx - minx
    height = maxy - miny
    extent = max(width, height)

    if extent > 40:
        zoom = 3
    elif extent > 20:
        zoom = 4
    elif extent > 10:
        zoom = 5
    elif extent > 5:
        zoom = 6
    else:
        zoom = 7

    return center, zoom


# ============================================================
# ENCABEZADO
# ============================================================
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.0rem;
            padding-bottom: 1rem;
        }

        .main-title {
            font-family: Arial, sans-serif;
            font-size: 30px;
            font-weight: 750;
            color: #12344D;
            margin-bottom: 2px;
        }

        .subtitle {
            color: #64748B;
            font-size: 14px;
            margin-bottom: 18px;
        }

        [data-testid="stSidebar"] {
            background-color: #F7F9FC;
        }

        .section-title {
            font-size: 14px;
            font-weight: 700;
            color: #12344D;
            margin-top: 8px;
            margin-bottom: 6px;
        }

        .metric-card {
            background: white;
            border: 1px solid #E5E7EB;
            border-radius: 10px;
            padding: 10px 14px;
            text-align: center;
        }
    </style>

    <div class="main-title">Visor Hidrológico Sudamérica</div>
    <div class="subtitle">
        Explorador geoespacial de cuencas, ríos, estaciones y límites territoriales
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# DESCUBRIR ARCHIVOS
# ============================================================
files = discover_files()

total_files = sum(len(v) for v in files.values())

if total_files == 0:
    st.error(
        "No se encontraron archivos .shp. "
        "Verifica que la carpeta data/ esté dentro del repositorio y tenga "
        "las subcarpetas cuenca/, rio/, estaciones/ y limite/."
    )
    st.stop()

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## Capas del mapa")
    st.caption("Selecciona las capas que deseas visualizar.")

    selected = {}

    for group_key, cfg in GROUPS.items():
        available = files[group_key]

        if not available:
            continue

        st.markdown(f"### {cfg['label']}")

        for i, path in enumerate(available):
            layer_id = f"{group_key}__{path.as_posix()}"

            default = group_key != "limite"

            selected[layer_id] = st.checkbox(
                nice_name(path),
                value=default,
                key=f"check_{hashlib.md5(layer_id.encode()).hexdigest()}",
            )

    st.divider()
    st.markdown("### Transparencia")

    polygon_opacity = st.slider(
        "Cuencas / límites",
        min_value=0.05,
        max_value=1.0,
        value=0.45,
        step=0.05,
    )

    line_opacity = st.slider(
        "Ríos",
        min_value=0.10,
        max_value=1.0,
        value=0.90,
        step=0.05,
    )

    point_opacity = st.slider(
        "Estaciones",
        min_value=0.10,
        max_value=1.0,
        value=0.95,
        step=0.05,
    )

    st.markdown("### Simbología")

    line_width = st.slider(
        "Grosor de ríos",
        min_value=1.0,
        max_value=8.0,
        value=3.0,
        step=0.5,
    )

    point_radius = st.slider(
        "Tamaño de estaciones",
        min_value=3,
        max_value=12,
        value=6,
        step=1,
    )

    st.divider()
    st.caption(
        f"Archivos espaciales encontrados: **{total_files}**"
    )

# ============================================================
# CREAR MAPA
# ============================================================
selected_layers = []
selected_gdfs = []

# Cargar primero todas las capas seleccionadas.
for group_key, cfg in GROUPS.items():
    for i, path in enumerate(files[group_key]):
        layer_id = f"{group_key}__{path.as_posix()}"

        if not selected.get(layer_id, False):
            continue

        try:
            gdf = load_layer(str(path))

            if gdf.empty:
                continue

            color = color_for_layer(i, group_key)

            if group_key == "limite" or cfg["geometry"] == "polygon":
                opacity = polygon_opacity
            elif cfg["geometry"] == "line":
                opacity = line_opacity
            else:
                opacity = point_opacity

            layer_name = f"{cfg['label']}: {nice_name(path)}"

            selected_layers.append(
                {
                    "name": layer_name,
                    "color": color,
                    "geometry": cfg["geometry"],
                }
            )
            selected_gdfs.append(gdf)

        except Exception as e:
            st.warning(
                f"No se pudo leer **{path.name}**: {e}"
            )

center, zoom = calculate_center(selected_gdfs)

m = folium.Map(
    location=center,
    zoom_start=zoom,
    control_scale=True,
    prefer_canvas=True,
    tiles=None,
)

# ============================================================
# MAPAS BASE
# ============================================================
# OpenStreetMap
folium.TileLayer(
    tiles="OpenStreetMap",
    name="Mapa callejero",
    control=True,
    show=True,
).add_to(m)

# Esri World Imagery = imagen satelital
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
          "World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri, Maxar, Earthstar Geographics",
    name="Imagen satelital",
    control=True,
    show=False,
).add_to(m)

# Esri World Street Map
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
          "World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attr="Esri",
    name="Mapa calles",
    control=True,
    show=False,
).add_to(m)

# ============================================================
# AGREGAR CAPAS
# ============================================================
layer_counter = 0

for group_key, cfg in GROUPS.items():
    for i, path in enumerate(files[group_key]):
        layer_id = f"{group_key}__{path.as_posix()}"

        if not selected.get(layer_id, False):
            continue

        try:
            gdf = load_layer(str(path))
            if gdf.empty:
                continue

            color = color_for_layer(i, group_key)

            if group_key == "limite" or cfg["geometry"] == "polygon":
                opacity = polygon_opacity
            elif cfg["geometry"] == "line":
                opacity = line_opacity
            else:
                opacity = point_opacity

            add_geodata_layer(
                m=m,
                gdf=gdf,
                layer_name=f"{cfg['label']}: {nice_name(path)}",
                geometry_type=cfg["geometry"],
                color=color,
                opacity=opacity,
                line_width=line_width,
                point_radius=point_radius,
            )

            layer_counter += 1

        except Exception:
            # El error ya fue mostrado en el bloque anterior.
            pass

# ============================================================
# CONTROLES DEL MAPA
# ============================================================
Fullscreen(
    position="topright",
    title="Pantalla completa",
    title_cancel="Salir de pantalla completa",
    force_separate_button=True,
).add_to(m)

MiniMap(
    tile_layer="OpenStreetMap",
    position="bottomright",
    toggle_display=True,
).add_to(m)

MousePosition(
    position="bottomright",
    separator=" | ",
    prefix="Coordenadas: ",
    lat_formatter="function(num) {return L.Util.formatNum(num, 5);}",
    lng_formatter="function(num) {return L.Util.formatNum(num, 5);}",
).add_to(m)

folium.LayerControl(
    position="topright",
    collapsed=False,
).add_to(m)

add_legend(m, selected_layers)

# ============================================================
# INDICADORES
# ============================================================
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#64748B;">Capas activas</div>
            <div style="font-size:23px;font-weight:700;color:#12344D;">
                {layer_counter}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c2:
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#64748B;">Cuencas</div>
            <div style="font-size:23px;font-weight:700;color:#2563EB;">
                {len(files["cuenca"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c3:
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#64748B;">Ríos</div>
            <div style="font-size:23px;font-weight:700;color:#1677FF;">
                {len(files["rio"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with c4:
    st.markdown(
        f"""
        <div class="metric-card">
            <div style="font-size:12px;color:#64748B;">Estaciones</div>
            <div style="font-size:23px;font-weight:700;color:#E63946;">
                {len(files["estaciones"])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("")

# ============================================================
# MAPA
# ============================================================
st_folium(
    m,
    width=None,
    height=720,
    returned_objects=[],
    use_container_width=True,
)
