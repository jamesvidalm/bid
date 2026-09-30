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
# CONFIGURACIÓN GENERAL
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
#
# data/
# ├── cuenca/
# ├── rio/
# ├── estaciones/
# └── limite/       <- NO SE USA
#
# El programa busca todos los .shp dentro de cuenca, rio y
# estaciones, incluyendo subcarpetas.

GROUPS = {
    "cuenca": {
        "label": "Cuencas analizadas",
        "folder": DATA_DIR / "cuenca",
        "geometry": "polygon",
    },
    "rio": {
        "label": "Ríos",
        "folder": DATA_DIR / "rio",
        "geometry": "line",
    },
    "estaciones": {
        "label": "Estaciones / Puntos",
        "folder": DATA_DIR / "estaciones",
        "geometry": "point",
    },
}

# ============================================================
# PALETAS
# ============================================================

# Muchos colores diferenciables para cuencas.
BASIN_COLORS = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#003F5C", "#58508D", "#BC5090", "#FF6361", "#FFA600",
    "#006D77", "#83C5BE", "#E29578", "#6A4C93", "#1982C4",
    "#8AC926", "#FFCA3A", "#FF595E", "#9B5DE5", "#00BBF9",
    "#00F5D4", "#F15BB5", "#4D908E", "#577590", "#F3722C",
    "#90BE6D", "#F9C74F", "#F94144", "#43AA8B", "#277DA1",
]

# Colores para puntos/estaciones.
STATION_COLORS = [
    "#E63946", "#1D3557", "#2A9D8F", "#F4A261", "#E76F51",
    "#6A4C93", "#1982C4", "#8AC926", "#FFCA3A", "#FF595E",
    "#00A6A6", "#7B2CBF", "#F72585", "#3A86FF", "#8338EC",
    "#FB5607", "#2EC4B6", "#011627", "#FF006E", "#3A0CA3",
    "#7209B7", "#4895EF", "#06D6A0", "#EF476F", "#118AB2",
    "#073B4C", "#8D99AE", "#D90429", "#2B2D42", "#0096C7",
    "#52B788", "#B5179E", "#4361EE", "#F77F00", "#2A9D8F",
]

# ============================================================
# FUNCIONES
# ============================================================

def nice_name(path: Path) -> str:
    """Nombre legible del archivo."""
    return path.stem.replace("_", " ").replace("-", " ").title()


def find_shapefiles(folder: Path):
    """
    Busca shapefiles recursivamente.

    EXCLUYE:
      - hybas_lake_sa_level01_v1c.shp ... level12
      - Hydro_RIVERS_v10.shp

    NO carga la carpeta data/limite.
    """
    if not folder.exists():
        return []

    shapefiles = []

    for shp in folder.rglob("*.shp"):
        stem_lower = shp.stem.lower()

        # ----------------------------------------------------
        # EXCLUSIÓN: HYBAS Level 01 hasta Level 12
        # ----------------------------------------------------
        if (
            stem_lower.startswith("hybas_lake_sa_level")
            and stem_lower.endswith("_v1c")
        ):
            level_text = stem_lower.replace(
                "hybas_lake_sa_level", ""
            ).replace("_v1c", "")

            if level_text.isdigit():
                level = int(level_text)
                if 1 <= level <= 12:
                    continue

        # ----------------------------------------------------
        # EXCLUSIÓN: Hydro_RIVERS_v10
        # ----------------------------------------------------
        if stem_lower == "hydro_rivers_v10":
            continue

        shapefiles.append(shp)

    return sorted(shapefiles, key=lambda p: p.name.lower())


@st.cache_data(show_spinner=False)
def discover_files():
    result = {}
    for key, cfg in GROUPS.items():
        result[key] = find_shapefiles(cfg["folder"])
    return result


@st.cache_data(show_spinner=True, ttl=3600)
def load_layer(path_str: str):
    """Lee el shapefile y lo transforma a WGS84."""
    gdf = gpd.read_file(path_str)

    if gdf.empty:
        return gdf

    if gdf.crs is not None:
        gdf = gdf.to_crs(epsg=4326)
    else:
        # No se inventa CRS si falta el .prj.
        st.warning(
            f"El archivo {Path(path_str).name} no tiene CRS (.prj)."
        )

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    return gdf


def safe_text(value):
    if pd.isna(value):
        return ""
    return html.escape(str(value))


def get_label_field(gdf):
    """
    Busca un campo razonable para identificar estaciones/puntos
    y elementos de cuenca.
    """
    preferred = [
        "nombre", "NOMBRE", "name", "NAME",
        "station", "STATION", "estacion", "ESTACION",
        "codigo", "CODIGO", "code", "CODE",
        "id", "ID", "site", "SITE"
    ]

    columns = [c for c in gdf.columns if c != "geometry"]

    for wanted in preferred:
        for col in columns:
            if str(col).lower() == wanted.lower():
                return col

    # Buscar por palabras clave.
    keywords = [
        "nombre", "name", "station", "estacion",
        "codigo", "code", "id"
    ]

    for col in columns:
        low = str(col).lower()
        if any(k in low for k in keywords):
            return col

    return columns[0] if columns else None


def popup_html(row, title="Información"):
    """Popup profesional con atributos."""
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
                    color:#334155;
                ">
                    {safe_text(col)}
                </td>
                <td style="
                    padding:5px 8px;
                    border-bottom:1px solid #E5E7EB;
                    color:#475569;
                ">
                    {safe_text(value)}
                </td>
            </tr>
            """
        )

    if not attrs:
        attrs.append(
            """
            <tr>
                <td colspan="2" style="padding:8px;">
                    Sin atributos disponibles
                </td>
            </tr>
            """
        )

    return f"""
    <div style="
        font-family:Arial,sans-serif;
        min-width:260px;
        max-width:450px;
    ">
        <div style="
            font-size:15px;
            font-weight:700;
            color:#12344D;
            margin-bottom:8px;
        ">
            {html.escape(title)}
        </div>

        <table style="
            border-collapse:collapse;
            width:100%;
            font-size:12px;
        ">
            {''.join(attrs)}
        </table>
    </div>
    """


def add_polygon_layer(
    m,
    gdf,
    layer_name,
    color_offset=0,
):
    """
    Dibuja cada polígono de la cuenca con un color diferente.
    La transparencia queda fija y NO aparece ningún control
    de transparencia en el sidebar.
    """
    fg = FeatureGroup(name=layer_name, show=True)

    label_field = get_label_field(gdf)

    for idx, (_, row) in enumerate(gdf.iterrows()):
        color = BASIN_COLORS[
            (color_offset + idx) % len(BASIN_COLORS)
        ]

        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        label = (
            str(row[label_field])
            if label_field is not None
            and not pd.isna(row[label_field])
            else f"Cuenca {idx + 1}"
        )

        popup = folium.Popup(
            popup_html(row, title=label),
            max_width=460,
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
                "fillOpacity": 0.48,
            },
            popup=popup,
            tooltip=folium.Tooltip(
                f"<b>Cuenca:</b> {html.escape(label)}"
            ),
        ).add_to(fg)

    fg.add_to(m)


def add_river_layer(
    m,
    gdf,
    layer_name,
):
    """Dibuja los ríos."""
    fg = FeatureGroup(name=layer_name, show=True)

    label_field = get_label_field(gdf)

    tooltip_fields = []
    if label_field is not None:
        tooltip_fields = [label_field]

    folium.GeoJson(
        gdf.to_json(),
        style_function=lambda feature: {
            "color": "#1769AA",
            "weight": 2.5,
            "opacity": 0.88,
        },
        highlight_function=lambda feature: {
            "color": "#0B4F71",
            "weight": 4,
            "opacity": 1,
        },
        tooltip=(
            folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=["Río:"],
                sticky=False,
            )
            if tooltip_fields
            else None
        ),
    ).add_to(fg)

    fg.add_to(m)


def add_station_layer(
    m,
    gdf,
    layer_name,
    color_offset=0,
):
    """
    Dibuja CADA punto con un color diferente.
    El color es individual para cada estación/punto,
    no un solo rojo para todo el shapefile.
    """
    fg = FeatureGroup(name=layer_name, show=True)

    label_field = get_label_field(gdf)

    for idx, (_, row) in enumerate(gdf.iterrows()):
        geom = row.geometry

        if geom is None or geom.is_empty:
            continue

        color = STATION_COLORS[
            (color_offset + idx) % len(STATION_COLORS)
        ]

        if geom.geom_type == "Point":
            points = [geom]
        elif geom.geom_type == "MultiPoint":
            points = list(geom.geoms)
        else:
            continue

        label = (
            str(row[label_field])
            if label_field is not None
            and not pd.isna(row[label_field])
            else f"Punto {idx + 1}"
        )

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
                    popup_html(row, title=label),
                    max_width=460,
                ),
                tooltip=folium.Tooltip(
                    f"<b>Estación:</b> {html.escape(label)}"
                ),
            ).add_to(fg)

    fg.add_to(m)


def calculate_center(all_gdfs):
    """Calcula centro y zoom inicial."""
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

    center = [
        (miny + maxy) / 2,
        (minx + maxx) / 2,
    ]

    extent = max(maxx - minx, maxy - miny)

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


def create_legend(basin_legend, station_legend, river_present):
    """
    Leyenda profesional:
      - Cuencas: color individual.
      - Estaciones: color individual.
      - Ríos: línea azul.
    """
    basin_html = ""

    if basin_legend:
        for item in basin_legend:
            basin_html += f"""
            <div style="
                display:flex;
                align-items:center;
                margin:5px 0;
                line-height:1.2;
            ">
                <span style="
                    display:inline-block;
                    width:18px;
                    height:13px;
                    background:{item['color']};
                    opacity:0.55;
                    border:2px solid {item['color']};
                    margin-right:8px;
                    flex-shrink:0;
                "></span>
                <span>{html.escape(item['label'])}</span>
            </div>
            """

    station_html = ""

    if station_legend:
        for item in station_legend:
            station_html += f"""
            <div style="
                display:flex;
                align-items:center;
                margin:5px 0;
                line-height:1.2;
            ">
                <span style="
                    display:inline-block;
                    width:11px;
                    height:11px;
                    border-radius:50%;
                    background:{item['color']};
                    border:2px solid white;
                    box-shadow:0 0 0 1px {item['color']};
                    margin-right:8px;
                    flex-shrink:0;
                "></span>
                <span>{html.escape(item['label'])}</span>
            </div>
            """

    river_html = ""

    if river_present:
        river_html = """
        <div style="
            display:flex;
            align-items:center;
            margin:5px 0;
        ">
            <span style="
                display:inline-block;
                width:25px;
                height:4px;
                background:#1769AA;
                margin-right:8px;
            "></span>
            <span>Ríos</span>
        </div>
        """

    if not basin_html and not station_html and not river_html:
        return

    sections = ""

    if basin_html:
        sections += f"""
        <div style="
            font-size:12px;
            font-weight:700;
            color:#12344D;
            margin:4px 0 7px;
        ">
            CUENCAS ANALIZADAS
        </div>
        {basin_html}
        """

    if river_html:
        sections += f"""
        <div style="
            font-size:12px;
            font-weight:700;
            color:#12344D;
            margin:12px 0 7px;
        ">
            HIDROGRAFÍA
        </div>
        {river_html}
        """

    if station_html:
        sections += f"""
        <div style="
            font-size:12px;
            font-weight:700;
            color:#12344D;
            margin:12px 0 7px;
        ">
            ESTACIONES / PUNTOS
        </div>
        {station_html}
        """

    legend = f"""
    <div style="
        position:fixed;
        bottom:25px;
        left:25px;
        z-index:9999;
        background:rgba(255,255,255,0.97);
        padding:14px 16px;
        border-radius:10px;
        box-shadow:0 3px 16px rgba(0,0,0,0.25);
        min-width:220px;
        max-width:330px;
        max-height:420px;
        overflow-y:auto;
        font-family:Arial,sans-serif;
        font-size:11px;
        color:#334155;
    ">
        <div style="
            font-size:14px;
            font-weight:700;
            color:#12344D;
            border-bottom:1px solid #DDE3EA;
            padding-bottom:8px;
            margin-bottom:9px;
        ">
            LEYENDA
        </div>
        {sections}
    </div>
    """

    macro = MacroElement()

    macro._template = Template(
        f"""
        {{% macro html(this, kwargs) %}}
        {legend}
        {{% endmacro %}}
        """
    )

    return macro


# ============================================================
# ESTILOS DE STREAMLIT
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

    .sidebar-section {
        font-size: 14px;
        font-weight: 700;
        color: #12344D;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# TÍTULO
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
# BUSCAR ARCHIVOS
# ============================================================

files = discover_files()

total_files = sum(len(v) for v in files.values())

if total_files == 0:
    st.error(
        """
        No se encontraron archivos .shp.

        Verifica que el repositorio tenga:

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
    if files["cuenca"]:

        st.markdown("### Cuencas analizadas")

        for path in files["cuenca"]:

            layer_id = (
                f"cuenca__{path.as_posix()}"
            )

            selected[layer_id] = st.checkbox(
                "Cuencas analizadas"
                if path.stem.lower() == "1era_salida"
                else nice_name(path),
                value=True,
                key=(
                    "check_"
                    + hashlib.md5(
                        layer_id.encode()
                    ).hexdigest()
                ),
            )

    # --------------------------------------------------------
    # RÍOS
    # --------------------------------------------------------
    if files["rio"]:

        st.markdown("### Ríos")

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

    # --------------------------------------------------------
    # ESTACIONES
    # --------------------------------------------------------
    if files["estaciones"]:

        st.markdown("### Estaciones / Puntos")

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

    st.divider()

    st.caption(
        "La simbología y transparencia de las cuencas "
        "se gestionan automáticamente."
    )


# ============================================================
# PRE-CARGAR CAPAS SELECCIONADAS
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

        except Exception as e:
            st.warning(
                f"No se pudo leer {path.name}: {e}"
            )


center, zoom = calculate_center(selected_gdfs)


# ============================================================
# CREAR MAPA
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

# Mapa callejero
folium.TileLayer(
    tiles="OpenStreetMap",
    name="Mapa callejero",
    control=True,
    show=True,
).add_to(m)


# Imagen satelital
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri, Maxar, Earthstar Geographics",
    name="Imagen satelital",
    control=True,
    show=False,
).add_to(m)


# Mapa de calles alternativo
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Mapa de calles",
    control=True,
    show=False,
).add_to(m)


# ============================================================
# DIBUJAR CAPAS
# ============================================================

basin_legend = []
station_legend = []
river_present = False

basin_color_index = 0
station_color_index = 0


# ------------------------------------------------------------
# CUENCAS
# ------------------------------------------------------------

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

        label_field = get_label_field(gdf)

        # Nombre de la capa.
        # 1era_salida -> Cuencas analizadas
        layer_name = (
            "Cuencas analizadas"
            if path.stem.lower() == "1era_salida"
            else nice_name(path)
        )

        fg = FeatureGroup(
            name=layer_name,
            show=True,
        )

        for idx, (_, row) in enumerate(
            gdf.iterrows()
        ):

            geom = row.geometry

            if geom is None or geom.is_empty:
                continue

            color = BASIN_COLORS[
                basin_color_index
                % len(BASIN_COLORS)
            ]

            basin_color_index += 1

            label = (
                str(row[label_field])
                if label_field is not None
                and not pd.isna(row[label_field])
                else f"Cuenca {idx + 1}"
            )

            basin_legend.append(
                {
                    "label": label,
                    "color": color,
                }
            )

            folium.GeoJson(
                geom.__geo_interface__,
                style_function=(
                    lambda feature, c=color: {
                        "color": c,
                        "weight": 1.8,
                        "opacity": 0.95,
                        "fillColor": c,
                        # Transparencia fija para cuencas.
                        "fillOpacity": 0.32,
                    }
                ),
                highlight_function=(
                    lambda feature, c=color: {
                        "color": c,
                        "weight": 3.2,
                        "opacity": 1,
                        "fillColor": c,
                        "fillOpacity": 0.48,
                    }
                ),
                popup=folium.Popup(
                    popup_html(
                        row,
                        title=label,
                    ),
                    max_width=460,
                ),
                tooltip=folium.Tooltip(
                    f"<b>Cuenca:</b> "
                    f"{html.escape(label)}"
                ),
            ).add_to(fg)

        fg.add_to(m)

    except Exception as e:
        st.warning(
            f"No se pudo cargar {path.name}: {e}"
        )


# ------------------------------------------------------------
# RÍOS
# ------------------------------------------------------------

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

        river_present = True

        add_river_layer(
            m=m,
            gdf=gdf,
            layer_name=nice_name(path),
        )

    except Exception as e:
        st.warning(
            f"No se pudo cargar {path.name}: {e}"
        )


# ------------------------------------------------------------
# ESTACIONES / PUNTOS
# ------------------------------------------------------------

for path in files["estaciones"]:

    layer_id = (
        f"estaciones__{path.as_posix()}"
    )

    if not selected.get(layer_id, False):
        continue

    try:
        gdf = load_layer(str(path))

        if gdf.empty:
            continue

        label_field = get_label_field(gdf)

        fg = FeatureGroup(
            name=nice_name(path),
            show=True,
        )

        for idx, (_, row) in enumerate(
            gdf.iterrows()
        ):

            geom = row.geometry

            if geom is None or geom.is_empty:
                continue

            if geom.geom_type == "Point":
                points = [geom]
            elif geom.geom_type == "MultiPoint":
                points = list(geom.geoms)
            else:
                continue

            color = STATION_COLORS[
                station_color_index
                % len(STATION_COLORS)
            ]

            station_color_index += 1

            label = (
                str(row[label_field])
                if label_field is not None
                and not pd.isna(row[label_field])
                else f"Punto {idx + 1}"
            )

            station_legend.append(
                {
                    "label": label,
                    "color": color,
                }
            )

            for point in points:

                folium.CircleMarker(
                    location=[
                        point.y,
                        point.x,
                    ],
                    radius=6,
                    color="#FFFFFF",
                    weight=2,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.95,
                    popup=folium.Popup(
                        popup_html(
                            row,
                            title=label,
                        ),
                        max_width=460,
                    ),
                    tooltip=folium.Tooltip(
                        f"<b>Estación:</b> "
                        f"{html.escape(label)}"
                    ),
                ).add_to(fg)

        fg.add_to(m)

    except Exception as e:
        st.warning(
            f"No se pudo cargar {path.name}: {e}"
        )


# ============================================================
# LEYENDA
# ============================================================

legend_macro = create_legend(
    basin_legend=basin_legend,
    station_legend=station_legend,
    river_present=river_present,
)

if legend_macro is not None:
    m.get_root().add_child(legend_macro)


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
# MAPA FINAL
# ============================================================

st_folium(
    m,
    width=None,
    height=760,
    returned_objects=[],
    use_container_width=True,
)
