import streamlit as st
import geopandas as gpd
import folium
from folium import FeatureGroup
from folium.plugins import Fullscreen, MousePosition, MiniMap
from streamlit_folium import st_folium
from pathlib import Path
from branca.element import MacroElement, Template
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

# ============================================================
# CARPETAS QUE SE UTILIZAN
# ============================================================
# En GitHub la carpeta puede llamarse "rio" o "rios".
# Se detecta automáticamente cuál existe.
RIVER_DIR = (
    DATA_DIR / "rio"
    if (DATA_DIR / "rio").exists()
    else DATA_DIR / "rios"
)

GROUPS = {
    "cuenca": {
        "label": "Cuencas analizadas",
        "folder": DATA_DIR / "cuenca",
        "geometry": "polygon",
    },
    "rio": {
        "label": "Ríos",
        "folder": RIVER_DIR,
        "geometry": "line",
    },
    "estaciones": {
        "label": "Estaciones / Puntos",
        "folder": DATA_DIR / "estaciones",
        "geometry": "point",
    },
}

# ============================================================
# COLORES
# ============================================================

# Cada cuenca/polígono mantiene un color diferente.
BASIN_COLORS = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#003F5C", "#58508D", "#BC5090", "#FF6361", "#FFA600",
    "#006D77", "#83C5BE", "#E29578", "#6A4C93", "#1982C4",
    "#8AC926", "#FFCA3A", "#FF595E", "#9B5DE5", "#00BBF9",
    "#00F5D4", "#F15BB5", "#4D908E", "#577590", "#F3722C",
    "#90BE6D", "#F9C74F", "#F94144", "#43AA8B", "#277DA1",
]

# IMPORTANTE:
# Un solo color por GRUPO de estaciones.
# Amaru = rojo
# Altimetría = azul
# BID = verde
# Si aparecen más grupos, se asignan colores adicionales.
STATION_GROUP_COLORS = [
    "#E63946",  # Amaru
    "#2563EB",  # Altimetría
    "#2A9D8F",  # BID
    "#F4A261",
    "#6A4C93",
    "#D97706",
    "#0891B2",
    "#DB2777",
    "#65A30D",
    "#7C3AED",
]

RIVER_COLOR = "#1769AA"

# ============================================================
# FUNCIONES
# ============================================================

def nice_name(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def find_shapefiles(folder: Path):
    """
    Busca todos los SHP dentro de una carpeta y subcarpetas.

    Excluye únicamente:
      - hybas_lake_sa_level01_v1c.shp ... level12
      - Hydro_RIVERS_v10.shp

    Todo lo demás se considera.
    """
    if not folder.exists():
        return []

    shapefiles = []

    # Acepta .shp en cualquier combinación de mayúsculas/minúsculas.
    for shp in folder.rglob("*"):
        if not shp.is_file() or shp.suffix.lower() != ".shp":
            continue

        stem = shp.stem.lower()

        # Excluir HYBAS Level 01-12
        if stem.startswith("hybas_lake_sa_level") and stem.endswith("_v1c"):
            level_text = stem.replace(
                "hybas_lake_sa_level", ""
            ).replace("_v1c", "")

            if level_text.isdigit():
                level = int(level_text)
                if 1 <= level <= 12:
                    continue

        # Excluir solamente este río
        if stem == "hydro_rivers_v10":
            continue

        shapefiles.append(shp)

    return sorted(shapefiles, key=lambda p: p.name.lower())


@st.cache_data(show_spinner=False)
def discover_files():
    return {
        key: find_shapefiles(cfg["folder"])
        for key, cfg in GROUPS.items()
    }


@st.cache_data(show_spinner=True, ttl=3600)
def load_layer(path_str: str):
    gdf = gpd.read_file(path_str)

    if gdf.empty:
        return gdf

    if gdf.crs is not None:
        gdf = gdf.to_crs(epsg=4326)

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    return gdf


def safe_text(value):
    if pd.isna(value):
        return ""
    return html.escape(str(value))


def find_field(gdf, candidates):
    """Busca un campo ignorando mayúsculas/minúsculas."""
    columns = [c for c in gdf.columns if c != "geometry"]

    for wanted in candidates:
        for col in columns:
            if str(col).lower() == wanted.lower():
                return col

    return None


def get_basin_id_field(gdf):
    """
    Busca específicamente el identificador de la cuenca.
    Se priorizan campos habituales de HYBAS.
    """
    field = find_field(
        gdf,
        [
            "HYBAS_ID",
            "HYBASID",
            "HYBAS_ID_1",
            "BASIN_ID",
            "BASINID",
            "ID",
            "Id",
            "id",
            "CODIGO",
            "CODIGO_ID",
            "CODE",
        ],
    )

    if field:
        return field

    # Búsqueda por nombre de columna
    for col in gdf.columns:
        if col == "geometry":
            continue

        low = str(col).lower()

        if (
            "hybas" in low
            or "basin" in low
            or low == "id"
            or "codigo" in low
            or "code" in low
        ):
            return col

    return None


def get_station_name_field(gdf):
    """Busca el campo que identifica una estación."""
    field = find_field(
        gdf,
        [
            "NOMBRE",
            "NOMBRE_EST",
            "ESTACION",
            "STATION",
            "NAME",
            "CODIGO",
            "COD_EST",
            "CODE",
            "ID",
            "id",
        ],
    )

    if field:
        return field

    for col in gdf.columns:
        if col == "geometry":
            continue

        low = str(col).lower()

        if (
            "nombre" in low
            or "estacion" in low
            or "station" in low
            or "name" in low
            or "codigo" in low
            or "code" in low
            or low == "id"
        ):
            return col

    return None


def popup_html(row, title):
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
                <td style="
                    font-weight:600;
                    padding:5px 8px;
                    border-bottom:1px solid #E5E7EB;
                    color:#334155;">
                    {safe_text(col)}
                </td>
                <td style="
                    padding:5px 8px;
                    border-bottom:1px solid #E5E7EB;
                    color:#475569;">
                    {safe_text(value)}
                </td>
            </tr>
            """
        )

    if not attrs:
        attrs.append(
            '<tr><td colspan="2">Sin atributos disponibles</td></tr>'
        )

    return f"""
    <div style="
        font-family:Arial,sans-serif;
        min-width:260px;
        max-width:450px;">
        <div style="
            font-size:15px;
            font-weight:700;
            color:#12344D;
            margin-bottom:8px;">
            {html.escape(str(title))}
        </div>
        <table style="
            border-collapse:collapse;
            width:100%;
            font-size:12px;">
            {''.join(attrs)}
        </table>
    </div>
    """


def add_basin_layers(m, gdf, layer_name, color_index):
    """
    Cada cuenca/polígono tiene su propio color.
    NO se agrega leyenda de cuencas.
    El ID aparece al pasar el cursor.
    """
    fg = FeatureGroup(name=layer_name, show=True)

    id_field = get_basin_id_field(gdf)

    for idx, (_, row) in enumerate(gdf.iterrows()):

        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        color = BASIN_COLORS[
            (color_index + idx) % len(BASIN_COLORS)
        ]

        if id_field is not None and not pd.isna(row[id_field]):
            basin_id = str(row[id_field])
        else:
            basin_id = str(idx + 1)

        # SOLO ID DE CUENCA AL PASAR EL CURSOR
        tooltip = folium.Tooltip(
            f"""
            <div style="
                font-family:Arial,sans-serif;
                font-size:13px;">
                <b>ID de cuenca:</b> {html.escape(basin_id)}
            </div>
            """,
            sticky=False,
        )

        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda feature, c=color: {
                "color": c,
                "weight": 1.8,
                "opacity": 0.95,
                "fillColor": c,
                "fillOpacity": 0.32,
            },
            highlight_function=lambda feature, c=color: {
                "color": c,
                "weight": 3.2,
                "opacity": 1,
                "fillColor": c,
                "fillOpacity": 0.45,
            },
            tooltip=tooltip,
            popup=folium.Popup(
                popup_html(
                    row,
                    f"Cuenca {basin_id}",
                ),
                max_width=450,
            ),
        ).add_to(fg)

    fg.add_to(m)


def add_river_layer(m, gdf, layer_name):
    """
    Agrega la capa de ríos.
    Se dibuja como línea y se coloca después de las cuencas para
    que quede visible sobre ellas.

    Si el archivo contiene MultiLineString, LineString o GeometryCollection,
    Folium/GeoJSON lo representa correctamente.
    """
    fg = FeatureGroup(name=layer_name, show=True)

    name_field = find_field(
        gdf,
        [
            "NOMBRE",
            "NAME",
            "RIVER",
            "RIVER_NAME",
            "NOMBRE_RIO",
            "RIVERNAME",
            "ID",
            "CODE",
        ],
    )

    # El GeoDataFrame completo se mantiene; no se filtran geometrías
    # porque algunos archivos pueden contener GeometryCollection.
    river_geojson = gdf.to_json()

    tooltip = None
    if name_field:
        tooltip = folium.GeoJsonTooltip(
            fields=[name_field],
            aliases=["Río:"],
            sticky=False,
            labels=True,
        )

    folium.GeoJson(
        river_geojson,
        name=layer_name,
        style_function=lambda feature: {
            "color": "#0057B8",
            "weight": 3.0,
            "opacity": 1.0,
        },
        highlight_function=lambda feature: {
            "color": "#003B7A",
            "weight": 5.0,
            "opacity": 1.0,
        },
        tooltip=tooltip,
    ).add_to(fg)

    fg.add_to(m)


def add_station_group(
    m,
    gdf,
    layer_name,
    color,
):
    """
    TODAS las estaciones de un SHAPE comparten un solo color.
    Ejemplo:
      Amaru = rojo
      Estaciones Altimetría = azul
      Estaciones BID = verde
    """
    fg = FeatureGroup(name=layer_name, show=True)

    name_field = get_station_name_field(gdf)

    for idx, (_, row) in enumerate(gdf.iterrows()):

        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        if geom.geom_type == "Point":
            points = [geom]
        elif geom.geom_type == "MultiPoint":
            points = list(geom.geoms)
        else:
            continue

        if name_field is not None and not pd.isna(row[name_field]):
            station_name = str(row[name_field])
        else:
            station_name = f"Punto {idx + 1}"

        for point in points:

            folium.CircleMarker(
                location=[point.y, point.x],
                radius=6,
                color="#FFFFFF",
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.95,
                popup=folium.Popup(
                    popup_html(
                        row,
                        station_name,
                    ),
                    max_width=450,
                ),
                tooltip=folium.Tooltip(
                    f"""
                    <b>{html.escape(layer_name)}</b><br>
                    {html.escape(station_name)}
                    """,
                    sticky=False,
                ),
            ).add_to(fg)

    fg.add_to(m)


def station_group_color(index, filename):
    """
    Determina el color por grupo de estaciones.
    Se fuerza:
      Amaru -> rojo
      Altimetria -> azul
      BID -> verde
    """
    low = filename.lower()

    if "amaru" in low:
        return "#E63946"

    if "altimetr" in low:
        return "#2563EB"

    if "bid" in low:
        return "#2A9D8F"

    return STATION_GROUP_COLORS[index % len(STATION_GROUP_COLORS)]


def calculate_center(gdfs):
    bounds = []

    for gdf in gdfs:
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

    center = [
        (miny + maxy) / 2,
        (minx + maxx) / 2,
    ]

    extent = max(
        maxx - minx,
        maxy - miny,
    )

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
# ESTILO
# ============================================================
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }

    .main-title {
        font-family: Arial, sans-serif;
        font-size: 30px;
        font-weight: 750;
        color: #12344D;
        margin-bottom: 3px;
    }

    .subtitle {
        color: #64748B;
        font-size: 14px;
        margin-bottom: 18px;
    }

    [data-testid="stSidebar"] {
        background-color: #F7F9FC;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# ENCABEZADO
# ============================================================
st.markdown(
    """
    <div class="main-title">
        Visor Hidrológico Sudamérica
    </div>
    <div class="subtitle">
        Explorador geoespacial de cuencas, ríos y estaciones hidrológicas
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DESCUBRIR ARCHIVOS
# ============================================================
files = discover_files()

total_files = sum(
    len(v) for v in files.values()
)

if total_files == 0:
    st.error(
        """
        No se encontraron shapefiles.

        Verifica:
        data/cuenca/
        data/rio/
        data/estaciones/
        """
    )
    st.stop()


# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:

    st.markdown("## Capas del mapa")

    st.caption(
        "Selecciona las capas que deseas visualizar."
    )

    selected = {}

    # --------------------------------------------------------
    # CUENCAS
    # --------------------------------------------------------
    st.markdown("### Cuencas analizadas")

    if files["cuenca"]:

        for path in files["cuenca"]:

            layer_id = (
                f"cuenca__{path.as_posix()}"
            )

            # 1era_salida se presenta como Cuencas analizadas
            label = (
                "Cuencas analizadas"
                if path.stem.lower() == "1era_salida"
                else nice_name(path)
            )

            selected[layer_id] = st.checkbox(
                label,
                value=True,
                key=(
                    "check_"
                    + hashlib.md5(
                        layer_id.encode()
                    ).hexdigest()
                ),
            )

    else:
        st.caption("No se encontraron cuencas.")

    # --------------------------------------------------------
    # RÍOS
    # --------------------------------------------------------
    st.markdown("### Ríos")

    if files["rio"]:

        for path in files["rio"]:

            layer_id = (
                f"rio__{path.as_posix()}"
            )

            selected[layer_id] = st.checkbox(
                nice_name(path),
                value=True,
                key=(
                    "check_"
                    + hashlib.md5(
                        layer_id.encode()
                    ).hexdigest()
                ),
            )

    else:
        st.warning(
            f"No hay SHP de ríos disponibles en "
            f"{GROUPS['rio']['folder'].relative_to(BASE_DIR)} "
            "después de excluir Hydro_RIVERS_v10.shp."
        )

    # --------------------------------------------------------
    # ESTACIONES
    # --------------------------------------------------------
    st.markdown("### Estaciones / Puntos")

    if files["estaciones"]:

        for path in files["estaciones"]:

            layer_id = (
                f"estaciones__{path.as_posix()}"
            )

            selected[layer_id] = st.checkbox(
                nice_name(path),
                value=True,
                key=(
                    "check_"
                    + hashlib.md5(
                        layer_id.encode()
                    ).hexdigest()
                ),
            )

    else:
        st.caption("No se encontraron estaciones.")


# ============================================================
# CAPAS SELECCIONADAS PARA CENTRAR EL MAPA
# ============================================================
selected_gdfs = []

for group_key, cfg in GROUPS.items():

    for path in files[group_key]:

        layer_id = (
            f"{group_key}__{path.as_posix()}"
        )

        if not selected.get(layer_id, False):
            continue

        try:
            gdf = load_layer(str(path))

            if not gdf.empty:
                selected_gdfs.append(gdf)

        except Exception:
            pass


center, zoom = calculate_center(
    selected_gdfs
)


# ============================================================
# MAPA
# ============================================================
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

folium.TileLayer(
    tiles="OpenStreetMap",
    name="Mapa callejero",
    control=True,
    show=True,
).add_to(m)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/"
        "ArcGIS/rest/services/World_Imagery/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri, Maxar, Earthstar Geographics",
    name="Imagen satelital",
    control=True,
    show=False,
).add_to(m)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/"
        "ArcGIS/rest/services/World_Street_Map/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Mapa de calles",
    control=True,
    show=False,
).add_to(m)


# ============================================================
# DIBUJAR CUENCAS
# ============================================================
basin_color_offset = 0

for path in files["cuenca"]:

    layer_id = (
        f"cuenca__{path.as_posix()}"
    )

    if not selected.get(layer_id, False):
        continue

    try:
        gdf = load_layer(str(path))

        if gdf.empty:
            continue

        layer_name = (
            "Cuencas analizadas"
            if path.stem.lower() == "1era_salida"
            else nice_name(path)
        )

        add_basin_layers(
            m=m,
            gdf=gdf,
            layer_name=layer_name,
            color_index=basin_color_offset,
        )

        basin_color_offset += len(gdf)

    except Exception as e:
        st.warning(
            f"No se pudo cargar {path.name}: {e}"
        )


# ============================================================
# DIBUJAR RÍOS
# ============================================================
for path in files["rio"]:

    layer_id = (
        f"rio__{path.as_posix()}"
    )

    if not selected.get(layer_id, False):
        continue

    try:
        gdf = load_layer(str(path))

        if gdf.empty:
            continue

        add_river_layer(
            m=m,
            gdf=gdf,
            layer_name=nice_name(path),
        )

    except Exception as e:
        st.warning(
            f"No se pudo cargar el río {path.name}: {e}"
        )


# ============================================================
# DIBUJAR ESTACIONES POR GRUPO
# ============================================================
for group_index, path in enumerate(
    files["estaciones"]
):

    layer_id = (
        f"estaciones__{path.as_posix()}"
    )

    if not selected.get(layer_id, False):
        continue

    try:
        gdf = load_layer(str(path))

        if gdf.empty:
            continue

        color = station_group_color(
            group_index,
            path.stem,
        )

        add_station_group(
            m=m,
            gdf=gdf,
            layer_name=nice_name(path),
            color=color,
        )

    except Exception as e:
        st.warning(
            f"No se pudo cargar {path.name}: {e}"
        )


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
    lat_formatter=(
        "function(num) {return L.Util.formatNum(num, 5);}"
    ),
    lng_formatter=(
        "function(num) {return L.Util.formatNum(num, 5);}"
    ),
).add_to(m)

folium.LayerControl(
    position="topright",
    collapsed=False,
).add_to(m)


# ============================================================
# MOSTRAR MAPA
# ============================================================
st_folium(
    m,
    width=None,
    height=760,
    returned_objects=[],
    use_container_width=True,
)
