
# -*- coding: utf-8 -*-

import os
import json
import hashlib
import warnings
from pathlib import Path

import streamlit as st
import geopandas as gpd
import pyogrio
import folium

from folium.plugins import Fullscreen, MousePosition, MiniMap
from streamlit_folium import st_folium

warnings.filterwarnings("ignore")

# ============================================================
# 1. CONFIGURACION
# ============================================================

st.set_page_config(
    page_title="Modelamiento Hidrológico Andino-Amazónico",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded"
)

ROOT = Path(__file__).resolve().parent

DIR_PUNTOS = ROOT / "puntos"
DIR_SUDAMERICA = ROOT / "sudamerica"
DIR_SUBCUENCAS = ROOT / "subcuencas"

TITULO = (
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

PALETA = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bcf60c",
    "#fabebe", "#008080", "#e6beff", "#9a6324",
    "#800000", "#aaffc3", "#808000", "#ffd8b1",
    "#000075", "#808080", "#1b9e77", "#d95f02",
    "#7570b3", "#e7298a", "#66a61e", "#e6ab02",
    "#a6761d", "#666666", "#17becf", "#bcbd22",
    "#8c564b", "#ff9896"
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
        key=lambda x: str(x).lower()
    )


@st.cache_data(show_spinner=False, max_entries=80)
def leer_shapefile(ruta, modificacion):
    return gpd.read_file(ruta, engine="pyogrio")


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
        raise ValueError("El archivo no tiene sistema de coordenadas.")

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    if gdf.empty:
        raise ValueError("No existen geometrías válidas.")

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
        aliases=[f"{c}:" for c in campos[:4]],
        sticky=True,
        localize=True
    )

    popup = folium.GeoJsonPopup(
        fields=campos,
        aliases=[f"{c}:" for c in campos],
        localize=True,
        max_width=350
    )

    return tooltip, popup


def convertir_geojson(gdf):
    # CORRECCION: json está importado al inicio del archivo.
    geojson = gdf.to_json(drop_id=True, na="null")
    return json.loads(geojson)


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
            "opacity": 0.95
        },

        highlight_function=lambda feature: {
            "color": "#ffffff",
            "weight": 2.5,
            "fillOpacity": 0.45
        },

        tooltip=tooltip,
        popup=popup,
        show=True

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
            fill_opacity=0.95
        ),

        tooltip=tooltip,
        popup=popup,
        show=True

    ).add_to(mapa)


def calcular_extension(lista_gdf):

    if not lista_gdf:
        return [-4.0, -75.0], None

    limites = []

    for gdf in lista_gdf:

        bounds = gdf.total_bounds

        if len(bounds) == 4 and all(
            map(lambda x: x == x, bounds)
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
# 3. CARGAR SHAPEFILES
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

            capas.append((archivo.stem, gdf))

        except Exception as error:

            errores.append(
                f"{etiqueta} / {archivo.name}: {error}"
            )

    return capas, errores


# ============================================================
# 4. CARGAR GEOPACKAGES
# ============================================================

def cargar_geopackages(archivos):

    capas = []
    errores = []

    for archivo in archivos:

        try:

            listado = pyogrio.list_layers(str(archivo))

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

                    capas.append((nombre_mapa, gdf))

                except Exception as error:

                    errores.append(
                        f"{archivo.name} / "
                        f"{nombre_capa}: {error}"
                    )

        except Exception as error:

            errores.append(
                f"{archivo.name}: {error}"
            )

    return capas, errores


# ============================================================
# 5. ENCABEZADO
# ============================================================

st.markdown(
    f"""
    <div style="
        background:linear-gradient(115deg,#082f49,#075985,#0f766e);
        padding:26px 30px;
        border-radius:13px;
        color:white;
        margin-bottom:18px;">

        <div style="
            font-size:12px;
            letter-spacing:2px;
            opacity:.85;">
            PLATAFORMA DE MODELAMIENTO HIDROLÓGICO
        </div>

        <h1 style="
            color:white;
            font-size:29px;
            margin:10px 0;">
            {TITULO}
        </h1>

        <div style="font-size:14px;opacity:.9;">
            Ecuador · Perú · Bolivia |
            Cuencas, subcuencas y estaciones
        </div>

    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# 6. DETECTAR ARCHIVOS
# ============================================================

archivos_puntos = buscar_archivos(
    DIR_PUNTOS, ".shp"
)

archivos_sudamerica = buscar_archivos(
    DIR_SUDAMERICA, ".shp"
)

archivos_gpkg = buscar_archivos(
    DIR_SUBCUENCAS, ".gpkg"
)


# ============================================================
# 7. PANEL LATERAL
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

st.sidebar.markdown("**Archivos detectados en GitHub**")

st.sidebar.write(
    f"Shapefiles de Sudamérica: {len(archivos_sudamerica)}"
)

st.sidebar.write(
    f"Shapefiles de puntos: {len(archivos_puntos)}"
)

st.sidebar.write(
    f"GeoPackages: {len(archivos_gpkg)}"
)

if st.sidebar.button(
    "🔄 Recargar archivos",
    use_container_width=True
):

    st.cache_data.clear()
    st.rerun()


# ============================================================
# 8. LEER CAPAS
# ============================================================

with st.spinner(
    "Leyendo archivos geoespaciales del repositorio..."
):

    capas_sudamerica, errores_base = cargar_shapefiles(
        archivos_sudamerica,
        "Sudamérica"
    )

    capas_puntos, errores_puntos = cargar_shapefiles(
        archivos_puntos,
        "Puntos"
    )

    capas_subcuencas, errores_gpkg = cargar_geopackages(
        archivos_gpkg
    )

errores = (
    errores_base
    + errores_puntos
    + errores_gpkg
)


# ============================================================
# 9. INDICADORES
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
# 10. VISOR GEoespacial
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
    prefer_canvas=True
)


# ============================================================
# 11. MAPAS BASE
# ============================================================

if ver_satelite:

    folium.TileLayer(
        tiles=(
            "https://mt1.google.com/vt/"
            "lyrs=s&x={x}&y={y}&z={z}"
        ),
        attr="Google Satellite",
        name="Google Satélite",
        overlay=False,
        show=True,
        max_zoom=20
    ).add_to(mapa)


folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=not ver_satelite
).add_to(mapa)


# ============================================================
# 12. CAPA SUDAMERICA
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
# 13. CUENCAS Y SUBCUENCAS
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
# 14. ESTACIONES
# ============================================================

if ver_puntos:

    for nombre, gdf in capas_puntos:

        agregar_puntos(
            mapa,
            gdf,
            nombre
        )


# ============================================================
# 15. CONTROLES DEL MAPA
# ============================================================

Fullscreen(
    position="topleft"
).add_to(mapa)

MousePosition(
    position="bottomright",
    prefix="Coordenadas",
    separator=" | ",
    num_digits=5
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
# 16. MOSTRAR MAPA
# ============================================================

try:

    st_folium(
        mapa,
        use_container_width=True,
        height=690,
        returned_objects=[],
        key="visor_hidrologico_bid"
    )

except Exception as error:

    st.error(
        f"Error al visualizar el mapa: {error}"
    )


# ============================================================
# 17. LEYENDA
# ============================================================

st.subheader("Leyenda de capas")

col1, col2 = st.columns(2)

with col1:

    st.markdown("**Límite geográfico**")

    st.markdown(
        '<span style="display:inline-block;width:14px;'
        'height:14px;background:#263746;margin-right:8px;"></span>'
        'Sudamérica',
        unsafe_allow_html=True
    )

    st.markdown("**Estaciones hidrológicas**")

    st.markdown(
        '<span style="display:inline-block;width:12px;'
        'height:12px;border-radius:50%;background:#e31a1c;'
        'margin-right:8px;"></span>'
        'Puntos de estaciones',
        unsafe_allow_html=True
    )


with col2:

    st.markdown("**Cuencas y subcuencas**")

    for nombre, _ in capas_subcuencas:

        color = color_estable(nombre)

        st.markdown(
            f'<span style="display:inline-block;width:14px;'
            f'height:14px;background:{color};'
            f'margin-right:8px;"></span>{nombre}',
            unsafe_allow_html=True
        )


# ============================================================
# 18. DIAGNOSTICO
# ============================================================

with st.expander(
    "Diagnóstico de lectura de archivos",
    expanded=bool(errores)
):

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
            f"Se encontraron {len(errores)} errores."
        )

        for error in errores:
            st.code(error)

    else:

        st.success(
            "Todos los archivos detectados "
            "se leyeron correctamente."
        )


# ============================================================
# 19. PIE DE PAGINA
# ============================================================

st.markdown(
    """
    <hr>

    <div style="
        text-align:center;
        color:#64748b;
        font-size:12px;">

        Modelamiento Hidrológico de las Cuencas
        Andino-Amazónicas · Ecuador · Perú · Bolivia

    </div>
    """,
    unsafe_allow_html=True
)
