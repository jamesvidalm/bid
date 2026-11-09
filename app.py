
import os
import warnings
from pathlib import Path

import streamlit as st
import geopandas as gpd
import pyogrio
import folium

from folium.plugins import Fullscreen, MousePosition, MiniMap
from streamlit_folium import st_folium

warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore")


# ============================================================
# 1. CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Modelamiento Hidrológico Andino-Amazónico",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT = Path(__file__).resolve().parent

DIR_PUNTOS = ROOT / "puntos"
DIR_SUDAMERICA = ROOT / "sudamerica"
DIR_SUBCUENCAS = ROOT / "subcuencas"

TITULO = (
    "Modelamiento Hidrológico de las Cuencas Andino-Amazónicas "
    "de Ecuador, Perú y Bolivia"
)

PALETA = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#808080", "#1b9e77", "#d95f02",
    "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d",
    "#666666", "#17becf", "#bcbd22", "#8c564b", "#ff9896",
]


# ============================================================
# 2. FUNCIONES AUXILIARES
# ============================================================

def color_estable(nombre):
    numero = int(
        hashlib.md5(nombre.encode("utf-8")).hexdigest()[:8],
        16
    )
    return PALETA[numero % len(PALETA)]


def buscar_archivos(carpeta, extension):

    if not carpeta.exists():
        return []

    return sorted(
        carpeta.rglob(f"*{extension}"),
        key=lambda ruta: str(ruta).lower()
    )


@st.cache_data(show_spinner=False, max_entries=80)
def leer_shapefile(ruta, modificacion):

    return gpd.read_file(
        ruta,
        engine="pyogrio"
    )


@st.cache_data(show_spinner=False, max_entries=150)
def leer_gpkg_capa(ruta, nombre_capa, modificacion):

    return gpd.read_file(
        ruta,
        layer=nombre_capa,
        engine="pyogrio"
    )


def preparar_gdf(gdf):

    if gdf is None or gdf.empty:
        raise ValueError("La capa no contiene registros.")

    if gdf.crs is None:
        raise ValueError("El archivo no tiene CRS definido.")

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    if gdf.empty:
        raise ValueError("No existen geometrías utilizables.")

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    try:
        gdf.geometry = gdf.geometry.simplify(
            tolerance=0.0003,
            preserve_topology=True
        )
    except Exception:
        pass

    return gdf.reset_index(drop=True)


def campos_visibles(gdf, limite=5):

    campos = []

    for campo in gdf.columns:

        if campo == gdf.geometry.name:
            continue

        try:
            if gdf[campo].notna().any():
                campos.append(campo)

        except Exception:
            continue

        if len(campos) >= limite:
            break

    return campos


def opciones_popup(gdf):

    campos = campos_visibles(gdf)

    if not campos:
        return None, None

    tooltip = folium.GeoJsonTooltip(
        fields=campos[:4],
        aliases=[f"{campo}:" for campo in campos[:4]],
        sticky=True,
        localize=True,
    )

    popup = folium.GeoJsonPopup(
        fields=campos,
        aliases=[f"{campo}:" for campo in campos],
        localize=True,
        max_width=350,
    )

    return tooltip, popup


def convertir_geojson(gdf):

    return json.loads(
        gdf.to_json(drop_id=True, na="null")
    )


# ============================================================
# 3. AGREGAR CAPAS AL MAPA
# ============================================================

def agregar_poligono(mapa, gdf, nombre, color):

    tooltip, popup = opciones_popup(gdf)

    folium.GeoJson(
        data=convertir_geojson(gdf),
        name=nombre,

        style_function=lambda feature, color=color: {
            "color": color,
            "weight": 1.2,
            "fillColor": color,
            "fillOpacity": 0.25,
            "opacity": 0.95,
        },

        highlight_function=lambda feature: {
            "color": "#ffffff",
            "weight": 2.5,
            "fillOpacity": 0.45,
        },

        tooltip=tooltip,
        popup=popup,
        show=True,

    ).add_to(mapa)


def agregar_puntos(mapa, gdf, nombre):

    tooltip, popup = opciones_popup(gdf)

    folium.GeoJson(
        data=convertir_geojson(gdf),
        name=nombre,

        marker=folium.CircleMarker(
            radius=5,
            color="#ffffff",
            weight=1,
            fill=True,
            fill_color="#e31a1c",
            fill_opacity=0.95,
        ),

        tooltip=tooltip,
        popup=popup,
        show=True,

    ).add_to(mapa)


# ============================================================
# 4. CALCULAR EXTENSIÓN DEL MAPA
# ============================================================

def calcular_extension(lista_gdf):

    if not lista_gdf:
        return [-4.0, -75.0], None

    limites = []

    for gdf in lista_gdf:

        bounds = gdf.total_bounds

        if (
            len(bounds) == 4
            and all(map(lambda x: x == x, bounds))
        ):
            limites.append(bounds)

    if not limites:
        return [-4.0, -75.0], None

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    centro = [
        (ymin + ymax) / 2,
        (xmin + xmax) / 2
    ]

    extension = [
        [ymin, xmin],
        [ymax, xmax]
    ]

    return centro, extension


# ============================================================
# 5. CARGAR SHAPEFILES
# ============================================================

def cargar_shapefiles(archivos, etiqueta):

    capas = []
    errores = []

    for archivo in archivos:

        try:

            gdf = leer_shapefile(
                str(archivo),
                archivo.stat().st_mtime
            )

            gdf = preparar_gdf(gdf)

            capas.append(
                (archivo.stem, gdf)
            )

        except Exception as error:

            errores.append(
                f"{etiqueta} / {archivo.name}: "
                f"{type(error).__name__}: {error}"
            )

    return capas, errores


# ============================================================
# 6. CARGAR GEOPACKAGES
# ============================================================

def cargar_geopackages(archivos):

    capas = []
    errores = []

    for archivo in archivos:

        try:

            listado = pyogrio.list_layers(
                str(archivo)
            )

            nombres_capas = [
                str(fila[0])
                for fila in listado
                if fila[0] is not None
            ]

            if not nombres_capas:

                errores.append(
                    f"{archivo.name}: no contiene capas."
                )

                continue

            for nombre_capa in nombres_capas:

                try:

                    gdf = leer_gpkg_capa(
                        str(archivo),
                        nombre_capa,
                        archivo.stat().st_mtime
                    )

                    gdf = preparar_gdf(gdf)

                    nombre_mapa = (
                        f"{archivo.stem} - {nombre_capa}"
                    )

                    capas.append(
                        (nombre_mapa, gdf)
                    )

                except Exception as error:

                    errores.append(
                        f"{archivo.name} / {nombre_capa}: "
                        f"{type(error).__name__}: {error}"
                    )

        except Exception as error:

            errores.append(
                f"{archivo.name}: "
                f"{type(error).__name__}: {error}"
            )

    return capas, errores


# ============================================================
# 7. ENCABEZADO
# ============================================================

st.markdown(
    f"""
    <div style="
        background:linear-gradient(115deg,#082f49,#075985,#0f766e);
        padding:26px 30px;
        border-radius:13px;
        color:white;
        margin-bottom:18px;">

        <div style="font-size:12px;letter-spacing:2px;opacity:.85;">
            PLATAFORMA DE MODELAMIENTO HIDROLÓGICO
        </div>

        <h1 style="color:white;font-size:29px;margin:10px 0;">
            {TITULO}
        </h1>

        <div style="font-size:14px;opacity:.9;">
            Ecuador · Perú · Bolivia |
            Cuencas, subcuencas y estaciones
        </div>

    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# 8. DETECTAR ARCHIVOS
# ============================================================

archivos_puntos = buscar_archivos(
    DIR_PUNTOS,
    ".shp"
)

archivos_sudamerica = buscar_archivos(
    DIR_SUDAMERICA,
    ".shp"
)

archivos_gpkg = buscar_archivos(
    DIR_SUBCUENCAS,
    ".gpkg"
)


# ============================================================
# 9. PANEL LATERAL
# ============================================================

st.sidebar.title("🗺️ Panel de capas")

ver_sudamerica = st.sidebar.checkbox(
    "Sudamérica",
    value=True
)

ver_puntos = st.sidebar.checkbox(
    "Estaciones hidrológicas",
    value=True
)

ver_cuencas = st.sidebar.checkbox(
    "Cuencas y subcuencas",
    value=True
)

ver_satelite = st.sidebar.checkbox(
    "Google Satélite",
    value=True
)

st.sidebar.divider()

st.sidebar.markdown(
    "**Archivos detectados en GitHub**"
)

st.sidebar.write(
    f"Shapefiles de Sudamérica: {len(archivos_sudamerica)}"
)

st.sidebar.write(
    f"Shapefiles de puntos: {len(archivos_puntos)}"
)

st.sidebar.write(
    f"GeoPackages de subcuencas: {len(archivos_gpkg)}"
)

if st.sidebar.button(
    "🔄 Recargar archivos",
    use_container_width=True
):

    st.cache_data.clear()
    st.rerun()


# ============================================================
# 10. VERIFICAR CARPETAS Y CARGAR CAPAS
# ============================================================

carpetas_faltantes = [
    nombre
    for nombre, ruta in [
        ("puntos", DIR_PUNTOS),
        ("sudamerica", DIR_SUDAMERICA),
        ("subcuencas", DIR_SUBCUENCAS),
    ]
    if not ruta.is_dir()
]

capas_sudamerica = []
capas_puntos = []
capas_subcuencas = []

errores = []

if carpetas_faltantes:

    st.error(
        "Faltan carpetas en la raíz del repositorio: "
        + ", ".join(carpetas_faltantes)
    )

    st.info(
        "Los nombres deben ser exactamente: "
        "puntos, sudamerica y subcuencas."
    )

else:

    with st.spinner(
        "Leyendo directamente los archivos del repositorio..."
    ):

        try:

            capas_sudamerica, e = cargar_shapefiles(
                archivos_sudamerica,
                "Sudamérica"
            )

            errores.extend(e)

        except Exception as error:

            errores.append(
                f"Error general leyendo Sudamérica: "
                f"{type(error).__name__}: {error}"
            )

        try:

            capas_puntos, e = cargar_shapefiles(
                archivos_puntos,
                "Puntos"
            )

            errores.extend(e)

        except Exception as error:

            errores.append(
                f"Error general leyendo puntos: "
                f"{type(error).__name__}: {error}"
            )

        try:

            capas_subcuencas, e = cargar_geopackages(
                archivos_gpkg
            )

            errores.extend(e)

        except Exception as error:

            errores.append(
                f"Error general leyendo GeoPackages: "
                f"{type(error).__name__}: {error}"
            )


if not archivos_sudamerica:

    errores.append(
        "No se encontraron archivos .shp "
        "dentro de la carpeta sudamerica."
    )

if not archivos_puntos:

    errores.append(
        "No se encontraron archivos .shp "
        "dentro de la carpeta puntos."
    )

if not archivos_gpkg:

    errores.append(
        "No se encontraron archivos .gpkg "
        "dentro de la carpeta subcuencas."
    )


# ============================================================
# 11. INDICADORES
# ============================================================

total_puntos = sum(
    len(gdf)
    for _, gdf in capas_puntos
)

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Capas de Sudamérica",
    len(capas_sudamerica)
)

c2.metric(
    "Estaciones",
    f"{total_puntos:,}"
)

c3.metric(
    "Archivos GPKG",
    len(archivos_gpkg)
)

c4.metric(
    "Capas hidrográficas",
    len(capas_subcuencas)
)


# ============================================================
# 12. CONSTRUIR MAPA
# ============================================================

st.subheader("Visor geoespacial")

todas = (
    [gdf for _, gdf in capas_sudamerica]
    + [gdf for _, gdf in capas_puntos]
    + [gdf for _, gdf in capas_subcuencas]
)

centro, bounds = calcular_extension(todas)

mapa = folium.Map(
    location=centro,
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True,
)


# ============================================================
# 13. MAPA SATELITAL
# ============================================================

if ver_satelite:

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google Satellite",
        name="Google Satélite",
        overlay=False,
        show=True,
        max_zoom=20,
    ).add_to(mapa)


folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=not ver_satelite,
).add_to(mapa)


# ============================================================
# 14. AGREGAR SUDAMÉRICA
# ============================================================

if ver_sudamerica:

    for nombre, gdf in capas_sudamerica:

        agregar_poligono(
            mapa,
            gdf,
            f"Sudamérica - {nombre}",
            "#263746"
        )


# ============================================================
# 15. AGREGAR CUENCAS Y SUBCUENCAS
# ============================================================

if ver_cuencas:

    for nombre, gdf in capas_subcuencas:

        agregar_poligono(
            mapa,
            gdf,
            nombre,
            color_estable(nombre)
        )


# ============================================================
# 16. AGREGAR ESTACIONES
# ============================================================

if ver_puntos:

    for nombre, gdf in capas_puntos:

        agregar_puntos(
            mapa,
            gdf,
            nombre
        )


# ============================================================
# 17. CONTROLES DEL MAPA
# ============================================================

Fullscreen(
    position="topleft"
).add_to(mapa)

MousePosition(
    position="bottomright",
    prefix="Coordenadas",
    separator=" | ",
    num_digits=5,
).add_to(mapa)

MiniMap(
    toggle_display=True,
    minimized=True
).add_to(mapa)

folium.LayerControl(
    collapsed=False
).add_to(mapa)

if bounds:

    mapa.fit_bounds(
        bounds,
        padding=(20, 20)
    )


# ============================================================
# 18. MOSTRAR MAPA
# ============================================================

try:

    st_folium(
        mapa,
        use_container_width=True,
        height=690,
        returned_objects=[],
        key="visor_hidrologico_bid",
    )

except Exception as error:

    st.error("No se pudo dibujar el mapa.")
    st.exception(error)


# ============================================================
# 19. LEYENDA
# ============================================================

st.subheader("Leyenda de capas")

col1, col2 = st.columns(2)

with col1:

    st.markdown("**Límite geográfico**")

    st.markdown(
        '<span style="display:inline-block;width:14px;height:14px;'
        'background:#263746;margin-right:8px;"></span>Sudamérica',
        unsafe_allow_html=True,
    )

    st.markdown("**Estaciones hidrológicas**")

    st.markdown(
        '<span style="display:inline-block;width:12px;height:12px;'
        'border-radius:50%;background:#e31a1c;margin-right:8px;"></span>'
        'Puntos de estaciones',
        unsafe_allow_html=True,
    )


with col2:

    st.markdown("**Cuencas y subcuencas**")

    for nombre, _ in capas_subcuencas:

        color = color_estable(nombre)

        st.markdown(
            f'<span style="display:inline-block;width:14px;height:14px;'
            f'background:{color};margin-right:8px;"></span>{nombre}',
            unsafe_allow_html=True,
        )


# ============================================================
# 20. DIAGNÓSTICO DE ARCHIVOS
# ============================================================

with st.expander(
    "Diagnóstico de lectura de archivos",
    expanded=bool(errores)
):

    st.write(f"Ruta de la aplicación: {ROOT}")

    st.write(
        f"Carpeta puntos existe: {DIR_PUNTOS.is_dir()}"
    )

    st.write(
        f"Carpeta sudamerica existe: {DIR_SUDAMERICA.is_dir()}"
    )

    st.write(
        f"Carpeta subcuencas existe: {DIR_SUBCUENCAS.is_dir()}"
    )

    st.write(
        f"Shapefiles de Sudamérica encontrados: "
        f"{len(archivos_sudamerica)}"
    )

    st.write(
        f"Shapefiles de puntos encontrados: "
        f"{len(archivos_puntos)}"
    )

    st.write(
        f"GeoPackages encontrados: "
        f"{len(archivos_gpkg)}"
    )

    st.write(
        f"Shapefiles de Sudamérica cargados: "
        f"{len(capas_sudamerica)}"
    )

    st.write(
        f"Shapefiles de puntos cargados: "
        f"{len(capas_puntos)}"
    )

    st.write(
        f"Capas internas de GPKG cargadas: "
        f"{len(capas_subcuencas)}"
    )

    if errores:

        st.warning(
            f"Se encontraron {len(errores)} errores de lectura."
        )

        for error in errores:

            st.code(error)

    else:

        st.success(
            "Todos los archivos detectados se leyeron correctamente."
        )


# ============================================================
# 21. PIE DE PÁGINA
# ============================================================

st.markdown(
    """
    <hr>

    <div style="
        text-align:center;
        color:#64748b;
        font-size:12px;">

        Modelamiento Hidrológico de las Cuencas Andino-Amazónicas
        · Ecuador · Perú · Bolivia

    </div>
    """,
    unsafe_allow_html=True,
)
