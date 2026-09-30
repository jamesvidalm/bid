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
    "limites": {
        "label": "Límites",
        "folder": DATA_DIR / "limite",
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
    Busca TODOS los shapefiles dentro de folder y subcarpetas.

    Excluye:
      - hybas_lake_sa_level01_v1c.shp ... level12
      - Hydro_RIVERS_v10.shp

    Se aceptan .shp, .SHP, .Shp, etc.
    """
    if not folder.exists() or not folder.is_dir():
        return []

    shapefiles = []

    for shp in folder.rglob("*"):
        if not shp.is_file():
            continue

        if shp.suffix.lower() != ".shp":
            continue

        stem = shp.stem.lower()

        # HYBAS Level 01-12
        if (
            stem.startswith("hybas_lake_sa_level")
            and stem.endswith("_v1c")
        ):
            level_text = (
                stem.replace("hybas_lake_sa_level", "")
                .replace("_v1c", "")
            )

            if level_text.isdigit():
                level = int(level_text)
                if 1 <= level <= 12:
                    continue

        # Excluir únicamente Hydro_RIVERS_v10
        if stem == "hydro_rivers_v10":
            continue

        shapefiles.append(shp)

    return sorted(
        shapefiles,
        key=lambda p: str(p).lower()
    )


def discover_files():
    """
    Descubre los shapefiles en cada grupo sin utilizar caché.

    Para ríos:
      1) busca en data/rio/
      2) busca en data/rios/
      3) si no encuentra nada, busca south_america_LOR.shp
         dentro de data/ como respaldo.

    Esto evita que el dashboard quede con una lista vacía
    cuando los archivos fueron subidos recientemente a GitHub.
    """
    result = {}

    # Cuencas
    result["cuenca"] = find_shapefiles(
        DATA_DIR / "cuenca"
    )

    # Límites
    result["limites"] = find_shapefiles(
        DATA_DIR / "limite"
    )

    # Estaciones
    result["estaciones"] = find_shapefiles(
        DATA_DIR / "estaciones"
    )

    # --------------------------------------------------------
    # RÍOS: buscar en ambas posibles carpetas
    # --------------------------------------------------------
    river_candidates = []

    for folder_name in ["rio", "rios"]:
        folder = DATA_DIR / folder_name

        for shp in find_shapefiles(folder):
            if shp not in river_candidates:
                river_candidates.append(shp)

    # --------------------------------------------------------
    # RESPALDO:
    # si no aparece en rio/rios, localizar específicamente
    # south_america_LOR.shp dentro de data/.
    # --------------------------------------------------------
    if not river_candidates and DATA_DIR.exists():

        for shp in DATA_DIR.rglob("*"):
            if not shp.is_file():
                continue

            if shp.suffix.lower() != ".shp":
                continue

            if shp.stem.lower() == "south_america_lor":
                river_candidates.append(shp)

    result["rio"] = sorted(
        river_candidates,
        key=lambda p: str(p).lower()
    )

    return result


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
            "weight": 0.5,
            "opacity": 1.0,
        },
        highlight_function=lambda feature: {
            "color": "#003B7A",
            "weight": 0.8,
            "opacity": 1.0,
        },
        tooltip=tooltip,
    ).add_to(fg)

    fg.add_to(m)


def add_limit_layer(m, gdf, layer_name):
    """
    Agrega la capa de límites administrativos/territoriales.
    Se muestra con una línea un poco más gruesa para que la
    delimitación sea claramente visible sobre las cuencas.
    """
    fg = FeatureGroup(name=layer_name, show=True)

    limit_geojson = gdf.to_json()

    folium.GeoJson(
        limit_geojson,
        name=layer_name,
        style_function=lambda feature: {
            "color": "#333333",
            "weight": 2.8,
            "opacity": 0.95,
            "fillOpacity": 0.0,
        },
        highlight_function=lambda feature: {
            "color": "#111111",
            "weight": 4.0,
            "opacity": 1.0,
            "fillOpacity": 0.02,
        },
    ).add_to(fg)

    fg.add_to(m)


def add_closure_station(m):
    """
    Estación de cierre:
    Puerto Alegría, Perú
    Coordenadas de la imagen:
      Latitud  = 4° 6' 53.83" S
      Longitud = 70° 3' 14.24" O

    Convertidas a grados decimales:
      Latitud  = -4.1149528
      Longitud = -70.0539556
    """
    lat = -4.1149528
    lon = -70.0539556
    layer_name = "Estación de cierre Peru - Puerto Alegria"

    fg = FeatureGroup(name=layer_name, show=True)

    folium.CircleMarker(
        location=[lat, lon],
        radius=9,
        color="#FFFFFF",
        weight=2.5,
        fill=True,
        fill_color="#7C3AED",
        fill_opacity=1.0,
        popup=folium.Popup(
            f"""
            <div style="font-family:Arial,sans-serif; min-width:260px;">
                <div style="
                    font-size:15px;
                    font-weight:700;
                    color:#12344D;
                    margin-bottom:8px;">
                    Estación de cierre Peru - Puerto Alegria
                </div>
                <table style="border-collapse:collapse; width:100%; font-size:12px;">
                    <tr>
                        <td style="font-weight:600; padding:5px 8px; border-bottom:1px solid #E5E7EB;">
                            Latitud
                        </td>
                        <td style="padding:5px 8px; border-bottom:1px solid #E5E7EB;">
                            -4.1149528
                        </td>
                    </tr>
                    <tr>
                        <td style="font-weight:600; padding:5px 8px;">
                            Longitud
                        </td>
                        <td style="padding:5px 8px;">
                            -70.0539556
                        </td>
                    </tr>
                </table>
            </div>
            """,
            max_width=400,
        ),
        tooltip=folium.Tooltip(
            "Estación de cierre Peru - Puerto Alegria",
            sticky=False,
        ),
    ).add_to(fg)

    # Etiqueta visible en el mapa
    folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(
            html="""
            <div style="
                font-family:Arial,sans-serif;
                font-size:12px;
                font-weight:700;
                color:#4C1D95;
                white-space:nowrap;
                margin-left:10px;
                margin-top:-8px;
                text-shadow:
                    -1px -1px 0 #fff,
                     1px -1px 0 #fff,
                    -1px  1px 0 #fff,
                     1px  1px 0 #fff;">
                Estación de cierre Peru - Puerto Alegria
            </div>
            """
        ),
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



# ============================================================
# RESUMEN DE ESTACIONES POR PAÍS
# ============================================================

COUNTRIES = ["Perú", "Bolivia", "Ecuador"]


def normalize_country(value):
    """Normaliza nombres de país a Perú, Bolivia o Ecuador."""
    if value is None or pd.isna(value):
        return None

    s = str(value).strip().lower()

    replacements = {
        "peru": "Perú",
        "perú": "Perú",
        "pe": "Perú",
        "per": "Perú",
        "bolivia": "Bolivia",
        "bo": "Bolivia",
        "ecuador": "Ecuador",
        "ec": "Ecuador",
    }

    return replacements.get(s)


@st.cache_data(show_spinner=False, ttl=86400)
def load_country_boundaries():
    """
    Carga límites nacionales de Perú, Bolivia y Ecuador.
    Se usa únicamente para determinar geográficamente el país
    donde está cada estación.

    Fuente pública: dataset GeoJSON de países.
    """
    url = (
        "https://raw.githubusercontent.com/"
        "datasets/geo-countries/master/data/countries.geojson"
    )

    try:
        countries = gpd.read_file(url)

        if countries.empty:
            return None

        if countries.crs is not None:
            countries = countries.to_crs(epsg=4326)

        country_field = find_field(
            countries,
            ["ADMIN", "NAME", "name", "COUNTRY", "Country", "SOVEREIGNT"]
        )

        if country_field is None:
            return None

        countries["pais_resumen"] = countries[country_field].apply(
            normalize_country
        )

        countries = countries[
            countries["pais_resumen"].isin(COUNTRIES)
        ].copy()

        if countries.empty:
            return None

        return countries[["pais_resumen", "geometry"]]

    except Exception:
        return None


def get_country_field(gdf):
    """Busca un campo de país si el propio shapefile de estaciones lo contiene."""
    return find_field(
        gdf,
        [
            "PAIS",
            "PAÍS",
            "PAIS_NAME",
            "COUNTRY",
            "COUNTRY_NAME",
            "NACION",
            "NATIONALITY",
        ],
    )


def assign_station_countries(gdf):
    """
    Asigna Perú, Bolivia o Ecuador a cada punto.

    Prioridad:
      1. Campo PAIS/COUNTRY del shapefile, si existe.
      2. Ubicación espacial contra límites nacionales.
    """
    result = gdf.copy()

    country_field = get_country_field(result)

    if country_field is not None:
        result["pais_resumen"] = result[country_field].apply(
            normalize_country
        )

        # Si todas las filas pudieron ser clasificadas, terminamos.
        if result["pais_resumen"].notna().all():
            return result

    # Clasificación espacial para los puntos que no tengan país.
    countries = load_country_boundaries()

    if countries is not None and not result.empty:
        try:
            points = result.copy()

            if points.crs is None:
                points = points.set_crs(epsg=4326)
            else:
                points = points.to_crs(epsg=4326)

            # Garantizar geometrías puntuales.
            points = points[
                points.geometry.geom_type.isin(["Point", "MultiPoint"])
            ].copy()

            if not points.empty:
                joined = gpd.sjoin(
                    points.drop(columns=["pais_resumen"], errors="ignore"),
                    countries,
                    how="left",
                    predicate="within",
                )

                # Mantener el índice original.
                country_values = joined["pais_resumen"]

                for idx, country in country_values.items():
                    if idx in result.index and pd.notna(country):
                        result.loc[idx, "pais_resumen"] = country

        except Exception:
            pass

    if "pais_resumen" not in result.columns:
        result["pais_resumen"] = None

    return result


def station_type_from_filename(path):
    """
    Determina si un archivo corresponde a Amaru, BID o Altimetría.
    """
    low = path.stem.lower()

    if "amaru" in low:
        return "Amaru"

    if "altimetr" in low:
        return "Altimetría"

    if "bid" in low:
        return "BID"

    return None


def build_station_summary(station_files):
    """
    Construye el resumen por país y tipo de estación.
    Cada registro representa una geometría puntual del shapefile.
    """
    rows = []

    for path in station_files:
        station_type = station_type_from_filename(path)

        # Solo se consideran los tres grupos solicitados.
        if station_type is None:
            continue

        try:
            gdf = load_layer(str(path))

            if gdf.empty:
                continue

            gdf = assign_station_countries(gdf)

            for _, row in gdf.iterrows():
                geom = row.geometry

                if geom is None or geom.is_empty:
                    continue

                if geom.geom_type == "Point":
                    rows.append(
                        {
                            "Pais": row.get("pais_resumen"),
                            "Tipo": station_type,
                        }
                    )

                elif geom.geom_type == "MultiPoint":
                    for _ in geom.geoms:
                        rows.append(
                            {
                                "Pais": row.get("pais_resumen"),
                                "Tipo": station_type,
                            }
                        )

        except Exception:
            continue

    # Tabla completa, garantizando siempre los tres países y tres tipos.
    base = pd.MultiIndex.from_product(
        [COUNTRIES, ["Amaru", "BID", "Altimetría"]],
        names=["Pais", "Tipo"],
    ).to_frame(index=False)

    if rows:
        data = pd.DataFrame(rows)

        data["Pais"] = data["Pais"].apply(normalize_country)

        data = data[
            data["Pais"].isin(COUNTRIES)
            & data["Tipo"].isin(["Amaru", "BID", "Altimetría"])
        ]

        counts = (
            data.groupby(["Pais", "Tipo"])
            .size()
            .reset_index(name="Cantidad")
        )

        base = base.merge(
            counts,
            on=["Pais", "Tipo"],
            how="left",
        )
    else:
        base["Cantidad"] = 0

    base["Cantidad"] = base["Cantidad"].fillna(0).astype(int)

    summary = (
        base.pivot(
            index="Pais",
            columns="Tipo",
            values="Cantidad",
        )
        .reindex(COUNTRIES)
        .fillna(0)
        .astype(int)
        .reset_index()
    )

    for col in ["Amaru", "BID", "Altimetría"]:
        if col not in summary.columns:
            summary[col] = 0

    summary["Total"] = (
        summary["Amaru"]
        + summary["BID"]
        + summary["Altimetría"]
    )

    return summary[
        ["Pais", "Amaru", "BID", "Altimetría", "Total"]
    ]


def build_station_list(station_files, selected_country):
    """Construye la lista nominal de estaciones del país seleccionado."""
    rows = []

    for path in station_files:
        station_type = station_type_from_filename(path)
        if station_type is None:
            continue

        try:
            gdf = load_layer(str(path))
            if gdf.empty:
                continue

            gdf = assign_station_countries(gdf)
            name_field = get_station_name_field(gdf)

            for idx, row in gdf.iterrows():
                country = row.get("pais_resumen")
                if normalize_country(country) != selected_country:
                    continue

                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue

                if name_field is not None:
                    raw_name = row.get(name_field)
                    if pd.notna(raw_name) and str(raw_name).strip():
                        station_name = str(raw_name).strip()
                    else:
                        station_name = f"Punto {idx + 1}"
                else:
                    station_name = f"Punto {idx + 1}"

                if geom.geom_type == "Point":
                    rows.append({
                        "Tipo de estación": station_type,
                        "Nombre de estación": station_name,
                    })
                elif geom.geom_type == "MultiPoint":
                    for point_idx, _ in enumerate(geom.geoms, start=1):
                        name_for_point = station_name
                        if station_name.startswith("Punto ") and len(geom.geoms) > 1:
                            name_for_point = f"{station_name} - {point_idx}"
                        rows.append({
                            "Tipo de estación": station_type,
                            "Nombre de estación": name_for_point,
                        })
        except Exception:
            continue

    if not rows:
        return pd.DataFrame(columns=["Tipo de estación", "Nombre de estación"])

    result = pd.DataFrame(rows)
    result = result.drop_duplicates(
        subset=["Tipo de estación", "Nombre de estación"],
        keep="first",
    )

    order = pd.CategoricalDtype(
        categories=["Amaru", "BID", "Altimetría"],
        ordered=True,
    )
    result["Tipo de estación"] = result["Tipo de estación"].astype(order)
    return result.sort_values(
        by=["Tipo de estación", "Nombre de estación"],
        kind="stable",
    ).reset_index(drop=True)


def show_station_summary(station_files):
    """Muestra el resumen de estaciones y el detalle nominal del país seleccionado."""

    summary = build_station_summary(station_files)

    st.markdown("## Resumen de estaciones")
    st.caption(
        "Cantidad de estaciones por país y grupo, según la ubicación geográfica de cada punto."
    )

    HEADER_BLUE = "#5B8EAD"
    HEADER_BLUE_DARK = "#4D7F9C"
    BORDER = "#D9E4EC"
    TEXT = "#334155"
    LIGHT_BLUE = "#F4F8FB"
    HOVER_BLUE = "#EAF2F7"
    TOTAL_BLUE = "#E5F0F6"

    def style_table(df, first_column_left=True, total_row=False, compact=False):
        font_size = "12px" if compact else "13px"
        cell_padding = "6px 9px" if compact else "8px 12px"
        header_padding = "7px 9px" if compact else "9px 12px"

        styler = (
            df.style
            .set_properties(
                **{
                    "font-family": "Arial, sans-serif",
                    "font-size": font_size,
                    "color": TEXT,
                    "text-align": "center",
                    "border": f"1px solid {BORDER}",
                    "padding": cell_padding,
                }
            )
            .set_table_styles(
                [
                    {
                        "selector": "table",
                        "props": [
                            ("width", "100%"),
                            ("border-collapse", "collapse"),
                            ("border-radius", "8px"),
                            ("overflow", "hidden"),
                            ("background-color", "white"),
                            ("box-shadow", "0 1px 4px rgba(18,52,77,0.08)"),
                            ("margin-bottom", "14px"),
                        ],
                    },
                    {
                        "selector": "th",
                        "props": [
                            ("background-color", HEADER_BLUE),
                            ("color", "white"),
                            ("font-weight", "700"),
                            ("text-align", "center"),
                            ("border", f"1px solid {HEADER_BLUE_DARK}"),
                            ("padding", header_padding),
                        ],
                    },
                    {
                        "selector": "tbody tr:nth-child(even) td",
                        "props": [("background-color", LIGHT_BLUE)],
                    },
                    {
                        "selector": "tbody tr:hover td",
                        "props": [("background-color", HOVER_BLUE)],
                    },
                ]
            )
            .hide(axis="index")
        )

        if first_column_left:
            styler = styler.set_properties(
                subset=pd.IndexSlice[:, [df.columns[0]]],
                **{
                    "text-align": "left",
                    "font-weight": "600",
                    "color": "#244B63",
                },
            )

        if total_row and len(df) > 0:
            styler = styler.set_properties(
                subset=pd.IndexSlice[[len(df) - 1], :],
                **{
                    "background-color": TOTAL_BLUE,
                    "font-weight": "700",
                    "color": "#1F465F",
                    "border-top": f"1px solid {BORDER}",
                },
            )

        return styler

    # ========================================================
    # TABLA 1: RESUMEN GENERAL
    # ========================================================
    st.markdown(
        '<div class="summary-table-title">Resumen por país</div>',
        unsafe_allow_html=True,
    )

    table_general = summary.rename(
        columns={
            "Pais": "País",
            "Amaru": "Amaru",
            "BID": "BID",
            "Altimetría": "Altimetría",
            "Total": "Total",
        }
    ).copy()

    for col in ["Amaru", "BID", "Altimetría", "Total"]:
        table_general[col] = table_general[col].astype(int)

    st.table(
        style_table(
            table_general,
            first_column_left=True,
            total_row=False,
            compact=True,
        )
    )

    # ========================================================
    # SELECTOR DE PAÍS
    # ========================================================
    selected_country = st.selectbox(
        "Selecciona un país para ver el detalle",
        COUNTRIES,
        index=0,
        key="station_country_selector",
    )

    selected_row = summary[summary["Pais"] == selected_country].copy()
    if selected_row.empty:
        return

    row = selected_row.iloc[0]

    # ========================================================
    # TABLA 2: DETALLE DEL PAÍS
    # ========================================================
    st.markdown(
        f'<div class="summary-table-title">Detalle de estaciones — {html.escape(selected_country)}</div>',
        unsafe_allow_html=True,
    )

    detail = pd.DataFrame(
        {
            "Tipo de estación": ["Amaru", "BID", "Altimetría", "Total"],
            "Cantidad": [
                int(row["Amaru"]),
                int(row["BID"]),
                int(row["Altimetría"]),
                int(row["Total"]),
            ],
        }
    )

    st.table(
        style_table(
            detail,
            first_column_left=True,
            total_row=True,
            compact=True,
        )
    )

    # ========================================================
    # LISTA NOMINAL EN 3 COLUMNAS
    # ========================================================
    st.markdown(
        f'<div class="summary-table-title">Estaciones de {html.escape(selected_country)}</div>',
        unsafe_allow_html=True,
    )

    st.caption(
        "Las estaciones se muestran separadas por grupo para facilitar su identificación."
    )

    station_list = build_station_list(station_files, selected_country)

    if station_list.empty:
        st.info(f"No se encontraron nombres de estaciones para {selected_country}.")
        return

    station_groups = {}
    for station_type in ["Amaru", "BID", "Altimetría"]:
        station_groups[station_type] = station_list[
            station_list["Tipo de estación"].astype(str) == station_type
        ]["Nombre de estación"].drop_duplicates().tolist()

    columns = st.columns(3, gap="medium")

    for col, station_type in zip(columns, ["Amaru", "BID", "Altimetría"]):
        names = station_groups[station_type]

        with col:
            st.markdown(
                f'''<div style="background:#5B8EAD;color:white;font-family:Arial,sans-serif;font-size:14px;font-weight:700;padding:8px 10px;border-radius:7px 7px 0 0;border:1px solid #4D7F9C;text-align:center;margin-top:4px;">{html.escape(station_type)} <span style="font-weight:400;">({len(names)})</span></div>''',
                unsafe_allow_html=True,
            )

            # Contenedor con altura fija y barra de desplazamiento vertical.
            # Así las listas largas (por ejemplo BID con 55 estaciones) no
            # hacen crecer demasiado la página.
            if names:
                rows_html = []
                for idx, name in enumerate(names, start=1):
                    safe_name = html.escape(str(name))
                    bg = "#F4F8FB" if idx % 2 == 0 else "#FFFFFF"
                    rows_html.append(
                        f'''<div style="display:flex;align-items:flex-start;gap:7px;padding:6px 8px;border-left:1px solid #D9E4EC;border-right:1px solid #D9E4EC;border-bottom:1px solid #D9E4EC;background:{bg};font-family:Arial,sans-serif;font-size:12px;line-height:1.25;color:#334155;"><span style="min-width:22px;color:#5B8EAD;font-weight:700;">{idx}.</span><span style="word-break:break-word;">{safe_name}</span></div>'''
                    )

                list_html = "".join(rows_html)

                st.markdown(
                    f'''<div style="height:390px;overflow-y:auto;overflow-x:hidden;border:1px solid #D9E4EC;border-top:0;border-radius:0 0 7px 7px;background:white;scrollbar-width:thin;scrollbar-color:#8AAEC2 #EEF4F8;">{list_html}</div>''',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '''<div style="height:390px;display:flex;align-items:center;justify-content:center;padding:10px 8px;border:1px solid #D9E4EC;border-top:0;border-radius:0 0 7px 7px;background:#F8FAFC;color:#64748B;font-family:Arial,sans-serif;font-size:12px;text-align:center;">Sin estaciones</div>''',
                    unsafe_allow_html=True,
                )


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
        padding-top: 3.2rem;
        padding-bottom: 1rem;
    }

    .main-title {
        font-family: Arial, sans-serif;
        font-size: 25px;
        line-height: 1.35;
        font-weight: 700;
        color: #12344D;
        margin: 0 0 20px 0;
        padding: 0;
        overflow: visible;
        white-space: normal;
        word-break: normal;
        overflow-wrap: normal;
    }

    [data-testid="stSidebar"] {
        background-color: #F7F9FC;
    }

    @media (max-width: 1200px) {
        .main-title {
            font-size: 23px;
            line-height: 1.3;
        }
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
        Modelamiento Hidrológico de las Cuencas
        Andino-Amazónicas de Ecuador, Perú y Bolivia
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
                ("Ríos principales" if path.stem.lower() == "south_america_lor" else nice_name(path)),
                value=True,
                key=(
                    "check_"
                    + hashlib.md5(
                        layer_id.encode()
                    ).hexdigest()
                ),
            )

    else:
        # No mostrar mensajes de error al usuario.
        # Si no hay archivos, simplemente no se agrega la sección.
        pass

    # --------------------------------------------------------
    # LÍMITES
    # --------------------------------------------------------
    st.markdown("### Límites")

    if files["limites"]:
        for path in files["limites"]:
            layer_id = (
                f"limites__{path.as_posix()}"
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
        st.caption("No se encontraron límites.")

    # --------------------------------------------------------
    # ESTACIÓN DE CIERRE
    # --------------------------------------------------------
    st.markdown("### Estación de cierre")

    closure_layer_id = "estacion_cierre__puerto_alegria"

    selected[closure_layer_id] = st.checkbox(
        "Estación de cierre Peru - Puerto Alegria",
        value=True,
        key="check_estacion_cierre_puerto_alegria",
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


# Incluir la estación de cierre en el cálculo del centro cuando está activa.
if selected.get("estacion_cierre__puerto_alegria", False):
    closure_gdf = gpd.GeoDataFrame(
        {"nombre": ["Estación de cierre Peru - Puerto Alegria"]},
        geometry=gpd.points_from_xy(
            [-70.0539556],
            [-4.1149528],
        ),
        crs="EPSG:4326",
    )
    selected_gdfs.append(closure_gdf)

center, zoom = calculate_center(
    selected_gdfs
)


# ============================================================
# RESUMEN DE ESTACIONES
# ============================================================
show_station_summary(files["estaciones"])


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
# DIBUJAR LÍMITES
# ============================================================
for path in files["limites"]:

    layer_id = (
        f"limites__{path.as_posix()}"
    )

    if not selected.get(layer_id, False):
        continue

    try:
        gdf = load_layer(str(path))

        if gdf.empty:
            continue

        add_limit_layer(
            m=m,
            gdf=gdf,
            layer_name=nice_name(path),
        )

    except Exception as e:
        st.warning(
            f"No se pudo cargar el límite {path.name}: {e}"
        )


# ============================================================
# DIBUJAR ESTACIÓN DE CIERRE
# ============================================================
if selected.get("estacion_cierre__puerto_alegria", False):
    add_closure_station(m)


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
