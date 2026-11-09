

# -*- coding: utf-8 -*-
"""
VISOR HIDROLÓGICO BID
Ecuador - Perú - Bolivia

Estructura del repositorio:
    app.py
    requirements.txt
    puntos/
    rios/
    subcuencas/
    sudamerica/

Lee archivos SHP y GPKG directamente desde GitHub.
Grafica todas las capas encontradas.
"""

from pathlib import Path
import hashlib
import html
import warnings

import streamlit as st
import geopandas as gpd
import pyogrio
import folium

from folium.plugins import Fullscreen
from streamlit_folium import st_folium

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
DIR_RIOS = ROOT / "rios"
DIR_SUBCUENCAS = ROOT / "subcuencas"
DIR_SUDAMERICA = ROOT / "sudamerica"

TITULO = (
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

PALETA = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231",
    "#911eb4", "#46f0f0", "#f032e6", "#bcf60c",
    "#008080", "#9a6324", "#800000", "#808000",
    "#000075", "#1b9e77", "#d95f02", "#7570b3",
    "#e7298a", "#66a61e", "#e6ab02", "#a6761d",
    "#17becf", "#8c564b", "#ff9896", "#393b79",
    "#637939", "#8c6d31", "#843c39", "#7b4173",
    "#3182bd", "#31a354", "#756bb1", "#636363",
]


# ============================================================
# 2. FUNCIONES GENERALES
# ============================================================

def color_estable(nombre):
    """Asigna un color constante según el nombre de la capa."""
    valor = int(
        hashlib.md5(
            nombre.encode("utf-8")
        ).hexdigest()[:8],
        16
    )
    return PALETA[valor % len(PALETA)]


def buscar_archivos(carpeta):
    """Busca SHP y GPKG recursivamente."""
    if not carpeta.exists():
        return []

    archivos = [
        archivo
        for archivo in carpeta.rglob("*")
        if archivo.is_file()
        and archivo.suffix.lower() in [".shp", ".gpkg"]
    ]

    return sorted(
        archivos,
        key=lambda x: str(x).lower()
    )


def nombre_relativo(archivo, carpeta):
    """Obtiene el nombre relativo dentro de una carpeta."""
    try:
        return archivo.relative_to(carpeta).with_suffix("").as_posix()
    except Exception:
        return archivo.stem


# ============================================================
# 3. LECTURA DE ARCHIVOS
# ============================================================

@st.cache_data(show_spinner=False, max_entries=100)
def leer_shapefile(ruta, modificacion):
    return gpd.read_file(
        ruta,
        engine="pyogrio"
    )


@st.cache_data(show_spinner=False, max_entries=200)
def leer_gpkg(ruta, nombre_capa, modificacion):
    return gpd.read_file(
        ruta,
        layer=nombre_capa,
        engine="pyogrio"
    )


def preparar_gdf(gdf, tipo):
    """Valida, reproyecta y simplifica geometrías."""

    if gdf is None or gdf.empty:
        raise ValueError("El archivo no contiene registros.")

    if gdf.crs is None:
        raise ValueError("El archivo no tiene CRS definido.")

    gdf = gdf[
        gdf.geometry.notna()
    ].copy()

    gdf = gdf[
        ~gdf.geometry.is_empty
    ].copy()

    if gdf.empty:
        raise ValueError("No existen geometrías válidas.")

    # Convertir a WGS84.
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Simplificar geometrías para reducir el peso del mapa.
    if tipo == "rios":
        tolerancia = 0.00015
    elif tipo == "puntos":
        tolerancia = 0
    else:
        tolerancia = 0.00025

    if tolerancia > 0:
        try:
            gdf.geometry = gdf.geometry.simplify(
                tolerance=tolerancia,
                preserve_topology=True
            )
        except Exception:
            pass

    # Eliminar columnas innecesarias de atributos.
    # Se conservan hasta cuatro atributos para los popups.
    geometria = gdf.geometry.name
    columnas = [
        c for c in gdf.columns
        if c != geometria
    ][:4]

    gdf = gdf[columnas + [geometria]].copy()

    return gdf.reset_index(drop=True)


def cargar_archivo(archivo, tipo, carpeta):
    """Carga SHP o todas las capas internas de un GPKG."""

    nombre_base = nombre_relativo(archivo, carpeta)
    modificacion = archivo.stat().st_mtime

    resultados = []

    if archivo.suffix.lower() == ".shp":

        gdf = leer_shapefile(
            str(archivo),
            modificacion
        )

        gdf = preparar_gdf(gdf, tipo)

        resultados.append(
            (nombre_base, gdf)
        )

    elif archivo.suffix.lower() == ".gpkg":

        listado = pyogrio.list_layers(
            str(archivo)
        )

        nombres = [
            str(fila[0])
            for fila in listado
            if fila[0] is not None
        ]

        for nombre_capa in nombres:

            gdf = leer_gpkg(
                str(archivo),
                nombre_capa,
                modificacion
            )

            gdf = preparar_gdf(gdf, tipo)

            if len(nombres) == 1:
                nombre_mapa = nombre_base
            else:
                nombre_mapa = (
                    f"{nombre_base} - {nombre_capa}"
                )

            resultados.append(
                (nombre_mapa, gdf)
            )

    return resultados


def cargar_carpeta(carpeta, tipo):
    """Carga todas las capas de una carpeta."""

    archivos = buscar_archivos(carpeta)

    capas = []
    errores = []

    for archivo in archivos:

        try:
            resultados = cargar_archivo(
                archivo,
                tipo,
                carpeta
            )

            capas.extend(resultados)

        except Exception as error:

            errores.append(
                f"{archivo.name}: {error}"
            )

    return capas, archivos, errores


# ============================================================
# 4. FUNCIONES DEL MAPA
# ============================================================

def campos_popup(gdf):
    """Obtiene los atributos disponibles para el popup."""

    return [
        columna
        for columna in gdf.columns
        if columna != gdf.geometry.name
    ][:4]


def agregar_poligono(mapa, gdf, nombre, color):

    campos = campos_popup(gdf)

    tooltip = None
    popup = None

    if campos:

        tooltip = folium.GeoJsonTooltip(
            fields=campos[:3],
            aliases=[
                f"{campo}:"
                for campo in campos[:3]
            ],
            sticky=True
        )

        popup = folium.GeoJsonPopup(
            fields=campos,
            aliases=[
                f"{campo}:"
                for campo in campos
            ],
            max_width=350
        )

    folium.GeoJson(
        data=gdf.to_json(drop_id=True),
        name=nombre,
        style_function=lambda feature, c=color: {
            "color": c,
            "weight": 1.2,
            "fillColor": c,
            "fillOpacity": 0.28,
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


def agregar_rios(mapa, gdf, nombre):

    campos = campos_popup(gdf)

    tooltip = None
    popup = None

    if campos:

        tooltip = folium.GeoJsonTooltip(
            fields=campos[:3],
            aliases=[
                f"{campo}:"
                for campo in campos[:3]
            ],
            sticky=True
        )

        popup = folium.GeoJsonPopup(
            fields=campos,
            aliases=[
                f"{campo}:"
                for campo in campos
            ],
            max_width=350
        )

    folium.GeoJson(
        data=gdf.to_json(drop_id=True),
        name=nombre,
        style_function=lambda feature: {
            "color": "#00BFFF",
            "weight": 2,
            "opacity": 0.95,
        },
        highlight_function=lambda feature: {
            "color": "#FFFF00",
            "weight": 4,
        },
        tooltip=tooltip,
        popup=popup,
        show=True,
    ).add_to(mapa)


def agregar_puntos(mapa, gdf, nombre):

    campos = campos_popup(gdf)

    tooltip = None
    popup = None

    if campos:

        tooltip = folium.GeoJsonTooltip(
            fields=campos[:3],
            aliases=[
                f"{campo}:"
                for campo in campos[:3]
            ],
            sticky=True
        )

        popup = folium.GeoJsonPopup(
            fields=campos,
            aliases=[
                f"{campo}:"
                for campo in campos
            ],
            max_width=350
        )

    folium.GeoJson(
        data=gdf.to_json(drop_id=True),
        name=nombre,
        marker=folium.CircleMarker(
            radius=4,
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


def calcular_extension(todas_las_capas):

    limites = []

    for _, gdf in todas_las_capas:

        try:
            bounds = gdf.total_bounds

            if len(bounds) == 4:
                limites.append(bounds)

        except Exception:
            continue

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
# 5. ENCABEZADO
# ============================================================

st.markdown(
    f"""
    <div style="
        background:linear-gradient(115deg,#082f49,#075985,#0f766e);
        padding:25px 30px;
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
            font-size:28px;
            margin:10px 0;">
            {TITULO}
        </h1>

        <div style="font-size:14px;opacity:.9;">
            Ecuador · Perú · Bolivia
        </div>
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# 6. DETECTAR ARCHIVOS
# ============================================================

archivos_sudamerica = buscar_archivos(
    DIR_SUDAMERICA
)

archivos_puntos = buscar_archivos(
    DIR_PUNTOS
)

archivos_rios = buscar_archivos(
    DIR_RIOS
)

archivos_subcuencas = buscar_archivos(
    DIR_SUBCUENCAS
)


# ============================================================
# 7. PANEL LATERAL
# ============================================================

st.sidebar.title("Panel de capas")

ver_sudamerica = st.sidebar.checkbox(
    "Sudamérica",
    value=True
)

ver_puntos = st.sidebar.checkbox(
    "Estaciones hidrológicas",
    value=True
)

ver_rios = st.sidebar.checkbox(
    "Ríos",
    value=True
)

ver_subcuencas = st.sidebar.checkbox(
    "Subcuencas",
    value=True
)

ver_satelite = st.sidebar.checkbox(
    "Google Satélite",
    value=True
)

st.sidebar.divider()

st.sidebar.markdown("**Archivos detectados**")

st.sidebar.write(
    f"Sudamérica: {len(archivos_sudamerica)}"
)

st.sidebar.write(
    f"Puntos: {len(archivos_puntos)}"
)

st.sidebar.write(
    f"Ríos: {len(archivos_rios)}"
)

st.sidebar.write(
    f"Subcuencas: {len(archivos_subcuencas)}"
)

if st.sidebar.button(
    "Recargar archivos",
    use_container_width=True
):
    st.cache_data.clear()
    st.rerun()


# ============================================================
# 8. CARGAR TODAS LAS CAPAS
# ============================================================

errores = []

with st.spinner(
    "Leyendo las capas geográficas del repositorio..."
):

    capas_sudamerica, _, errores_sudamerica = cargar_carpeta(
        DIR_SUDAMERICA,
        "sudamerica"
    )

    capas_puntos, _, errores_puntos = cargar_carpeta(
        DIR_PUNTOS,
        "puntos"
    )

    capas_rios, _, errores_rios = cargar_carpeta(
        DIR_RIOS,
        "rios"
    )

    capas_subcuencas, _, errores_subcuencas = cargar_carpeta(
        DIR_SUBCUENCAS,
        "subcuencas"
    )

errores.extend(errores_sudamerica)
errores.extend(errores_puntos)
errores.extend(errores_rios)
errores.extend(errores_subcuencas)


# ============================================================
# 9. INDICADORES
# ============================================================

total_estaciones = sum(
    len(gdf)
    for _, gdf in capas_puntos
)

total_elementos_rios = sum(
    len(gdf)
    for _, gdf in capas_rios
)

total_elementos_subcuencas = sum(
    len(gdf)
    for _, gdf in capas_subcuencas
)

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Estaciones",
    f"{total_estaciones:,}"
)

c2.metric(
    "Capas de ríos",
    len(capas_rios)
)

c3.metric(
    "Subcuencas",
    len(capas_subcuencas)
)

c4.metric(
    "Capas Sudamérica",
    len(capas_sudamerica)
)


# ============================================================
# 10. CONSTRUIR MAPA
# ============================================================

st.subheader("Visor geoespacial")

capas_extension = (
    capas_sudamerica
    + capas_puntos
    + capas_rios
    + capas_subcuencas
)

centro, bounds = calcular_extension(
    capas_extension
)

mapa = folium.Map(
    location=centro,
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True,
)

# Google Satélite.
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satélite",
    overlay=False,
    show=ver_satelite,
    max_zoom=20,
).add_to(mapa)

# OpenStreetMap.
folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=not ver_satelite,
).add_to(mapa)


# ============================================================
# 11. DIBUJAR SUDAMÉRICA
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
# 12. DIBUJAR SUBCUENCAS
# ============================================================

if ver_subcuencas:

    for nombre, gdf in capas_subcuencas:

        color = color_estable(nombre)

        agregar_poligono(
            mapa,
            gdf,
            nombre,
            color
        )


# ============================================================
# 13. DIBUJAR RÍOS
# ============================================================

if ver_rios:

    for nombre, gdf in capas_rios:

        agregar_rios(
            mapa,
            gdf,
            nombre
        )


# ============================================================
# 14. DIBUJAR ESTACIONES
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

st_folium(
    mapa,
    use_container_width=True,
    height=720,
    returned_objects=[],
    key="visor_hidrologico_bid",
)


# ============================================================
# 17. LEYENDA
# ============================================================

st.subheader("Leyenda")

elementos_leyenda = []

if ver_sudamerica and capas_sudamerica:

    elementos_leyenda.append(
        ("#263746", "Límite de Sudamérica", "polygon")
    )

if ver_puntos and capas_puntos:

    elementos_leyenda.append(
        ("#e31a1c", "Estaciones hidrológicas", "point")
    )

if ver_rios and capas_rios:

    elementos_leyenda.append(
        ("#00BFFF", "Red hidrográfica - Ríos", "line")
    )

if ver_subcuencas:

    for nombre, _ in capas_subcuencas:

        elementos_leyenda.append(
            (
                color_estable(nombre),
                nombre,
                "polygon"
            )
        )

if elementos_leyenda:

    contenido_leyenda = []

    for color, nombre, tipo in elementos_leyenda:

        nombre_seguro = html.escape(str(nombre))

        if tipo == "point":

            simbolo = (
                f'<span style="display:inline-block;'
                f'width:11px;height:11px;border-radius:50%;'
                f'background:{color};margin-right:8px;"></span>'
            )

        elif tipo == "line":

            simbolo = (
                f'<span style="display:inline-block;'
                f'width:22px;height:3px;'
                f'background:{color};margin-right:8px;'
                f'vertical-align:middle;"></span>'
            )

        else:

            simbolo = (
                f'<span style="display:inline-block;'
                f'width:13px;height:13px;'
                f'background:{color};margin-right:8px;"></span>'
            )

        contenido_leyenda.append(
            f'<div style="margin:5px 0;">'
            f'{simbolo}{nombre_seguro}</div>'
        )

    st.markdown(
        f"""
        <div style="
            border:1px solid #d1d5db;
            border-radius:8px;
            padding:12px 16px;
            max-height:300px;
            overflow-y:auto;
            font-size:13px;">
            {''.join(contenido_leyenda)}
        </div>
        """,
        unsafe_allow_html=True
    )

else:

    st.info("No hay capas seleccionadas para mostrar en la leyenda.")


# ============================================================
# 18. DIAGNÓSTICO
# ============================================================

with st.expander("Diagnóstico de archivos"):

    st.write(
        f"Capas de Sudamérica: {len(capas_sudamerica)}"
    )

    st.write(
        f"Capas de puntos: {len(capas_puntos)}"
    )

    st.write(
        f"Capas de ríos: {len(capas_rios)}"
    )

    st.write(
        f"Capas de subcuencas: {len(capas_subcuencas)}"
    )

    st.write(
        f"Elementos de ríos: {total_elementos_rios:,}"
    )

    st.write(
        f"Elementos de subcuencas: {total_elementos_subcuencas:,}"
    )

    if errores:

        st.warning(
            f"Se encontraron {len(errores)} errores."
        )

        for error in errores:
            st.code(error)

    else:

        st.success(
            "Todos los archivos se leyeron correctamente."
        )


# ============================================================
# 19. PIE DE PÁGINA
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

