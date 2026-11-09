
# -*- coding: utf-8 -*-

from pathlib import Path
import hashlib
import warnings

import streamlit as st
import geopandas as gpd
import pyogrio
import folium

from shapely.geometry import Point
from folium.plugins import Fullscreen
from streamlit_folium import st_folium

warnings.filterwarnings("ignore")

# ============================================================
# 1. CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Visor Hidrológico BID",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT = Path(__file__).resolve().parent

CARPETAS = {
    "puntos": ROOT / "puntos",
    "rios": ROOT / "rios",
    "subcuencas": ROOT / "subcuencas",
    "sudamerica": ROOT / "sudamerica",
}

PALETA = [
    "#77A6A1", "#9A8DB4", "#BCA078", "#85A9C7",
    "#B68F9F", "#9DB27E", "#8E9EBC", "#C0A58B",
    "#78B2AA", "#A59B78", "#90B1A0", "#B49AC0",
    "#87A4BC", "#AAB78C", "#C0A0A0", "#83AFA1",
    "#A5A0C0", "#C2B080", "#8DB9B1", "#B3A3A0",
]

# Colores de selección.
COLOR_CUENCA_ACTIVA = "#F4B400"
COLOR_RIO_ACTIVO = "#00BFFF"
COLOR_RIO_NORMAL = "#8FB9C9"
COLOR_ESTACION = "#D9534F"
COLOR_ESTACION_ACTIVA = "#FFD000"


# ============================================================
# 2. FUNCIONES DE ARCHIVOS
# ============================================================

def buscar_archivos(carpeta):

    if not carpeta.exists():
        return []

    return sorted(
        [
            p for p in carpeta.rglob("*")
            if p.is_file()
            and p.suffix.lower() in (".shp", ".gpkg")
        ],
        key=lambda p: str(p).lower()
    )


def color_cuenca(nombre):

    valor = int(
        hashlib.md5(
            nombre.encode("utf-8")
        ).hexdigest()[:8],
        16
    )

    return PALETA[valor % len(PALETA)]


@st.cache_data(
    show_spinner=False,
    max_entries=30
)
def leer_archivo(ruta, capa, modificacion):

    if capa is None:
        return gpd.read_file(
            ruta,
            engine="pyogrio"
        )

    return gpd.read_file(
        ruta,
        layer=capa,
        engine="pyogrio"
    )


@st.cache_data(
    show_spinner=False,
    max_entries=300
)
def preparar_archivo(
    ruta,
    capa,
    modificacion,
    tipo
):

    gdf = leer_archivo(
        ruta,
        capa,
        modificacion
    )

    if gdf.empty:
        return None

    if gdf.crs is None:
        raise ValueError("El archivo no tiene CRS.")

    gdf = gdf[
        gdf.geometry.notna()
    ].copy()

    gdf = gdf[
        ~gdf.geometry.is_empty
    ].copy()

    if gdf.empty:
        return None

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    tolerancias = {
        "puntos": 0,
        "rios": 0.0002,
        "subcuencas": 0.0004,
        "sudamerica": 0.001,
    }

    tolerancia = tolerancias.get(tipo, 0)

    if tolerancia > 0:
        try:
            gdf.geometry = gdf.geometry.simplify(
                tolerance=tolerancia,
                preserve_topology=True
            )
        except Exception:
            pass

    # Conservar geometría y hasta tres atributos.
    geom_col = gdf.geometry.name

    atributos = [
        c for c in gdf.columns
        if c != geom_col
    ][:3]

    gdf = gdf[
        atributos + [geom_col]
    ].copy()

    return gdf.reset_index(drop=True)


def cargar_carpeta(tipo):

    carpeta = CARPETAS[tipo]

    capas = []
    errores = []

    for archivo in buscar_archivos(carpeta):

        try:

            nombre_base = (
                archivo.relative_to(carpeta)
                .with_suffix("")
                .as_posix()
            )

            if archivo.suffix.lower() == ".gpkg":

                listado = pyogrio.list_layers(
                    str(archivo)
                )

                capas_internas = [
                    str(fila[0])
                    for fila in listado
                    if fila[0] is not None
                    and str(fila[1]).lower() != "none"
                ]

            else:
                capas_internas = [None]

            for capa in capas_internas:

                try:

                    gdf = preparar_archivo(
                        str(archivo),
                        capa,
                        archivo.stat().st_mtime,
                        tipo
                    )

                    if gdf is None:
                        continue

                    nombre = nombre_base

                    if (
                        capa is not None
                        and len(capas_internas) > 1
                    ):
                        nombre = f"{nombre_base} - {capa}"

                    capas.append(
                        (nombre, gdf)
                    )

                except Exception as e:

                    errores.append(
                        f"{archivo.name} / {capa}: {e}"
                    )

        except Exception as e:

            errores.append(
                f"{archivo.name}: {e}"
            )

    return capas, errores


# ============================================================
# 3. FUNCIONES GEOGRÁFICAS
# ============================================================

def buscar_estacion(lat, lon, capas_puntos):

    punto = Point(lon, lat)

    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_puntos:

        for indice, geom in enumerate(gdf.geometry):

            if geom.geom_type != "Point":
                continue

            distancia = geom.distance(punto)

            if distancia < distancia_minima:

                distancia_minima = distancia
                mejor = (nombre, indice, geom)

    # Tolerancia aproximada de 2 km en latitud.
    if distancia_minima > 0.02:
        return None

    return mejor


def buscar_cuenca(lat, lon, capas_subcuencas):

    punto = Point(lon, lat)

    # Priorizar cuencas que contienen el punto.
    candidatas = []

    for nombre, gdf in capas_subcuencas:

        try:

            mascara = gdf.geometry.covers(punto)

            if mascara.any():

                for indice in gdf.index[mascara]:

                    geom = gdf.geometry.loc[indice]

                    candidatas.append(
                        (
                            geom.area,
                            nombre,
                            int(indice)
                        )
                    )

        except Exception:
            continue

    if candidatas:

        # Seleccionar la cuenca de menor superficie
        # si hay polígonos superpuestos.
        candidatas.sort(key=lambda x: x[0])

        return (
            candidatas[0][1],
            candidatas[0][2]
        )

    # Buscar cuenca cercana cuando el punto
    # está ligeramente fuera del polígono.
    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_subcuencas:

        try:

            distancias = gdf.geometry.distance(punto)

            indice = distancias.idxmin()
            distancia = float(distancias.loc[indice])

            if distancia < distancia_minima:

                distancia_minima = distancia
                mejor = (
                    nombre,
                    int(indice)
                )

        except Exception:
            continue

    if distancia_minima <= 0.02:
        return mejor

    return None


def obtener_poligono(seleccion, capas_subcuencas):

    if seleccion is None:
        return None

    nombre_buscado, indice_buscado = seleccion

    for nombre, gdf in capas_subcuencas:

        if nombre == nombre_buscado:

            if indice_buscado in gdf.index:
                return gdf.geometry.loc[indice_buscado]

    return None


def extension_general(capas):

    limites = []

    for _, gdf in capas:

        if not gdf.empty:

            try:
                limites.append(gdf.total_bounds)
            except Exception:
                pass

    if not limites:

        return [
            [-20, -82],
            [5, -60]
        ]

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    return [
        [ymin, xmin],
        [ymax, xmax]
    ]


# ============================================================
# 4. ESTADO DE SELECCIÓN
# ============================================================

if "estacion_activa" not in st.session_state:
    st.session_state.estacion_activa = None

if "cuenca_activa" not in st.session_state:
    st.session_state.cuenca_activa = None

if "ultimo_clic" not in st.session_state:
    st.session_state.ultimo_clic = None


# ============================================================
# 5. ENCABEZADO
# SIN HTML
# ============================================================

st.title(
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

st.caption(
    "Ecuador · Perú · Bolivia | "
    "Estaciones, subcuencas y red hidrográfica"
)


# ============================================================
# 6. PANEL LATERAL
# ============================================================

st.sidebar.title("Panel de capas")

ver_sudamerica = st.sidebar.checkbox(
    "Sudamérica",
    value=True
)

ver_subcuencas = st.sidebar.checkbox(
    "Subcuencas",
    value=True
)

ver_rios = st.sidebar.checkbox(
    "Ríos",
    value=True
)

ver_puntos = st.sidebar.checkbox(
    "Estaciones hidrológicas",
    value=True
)

ver_satelite = st.sidebar.checkbox(
    "Google Satélite",
    value=True
)

st.sidebar.divider()

if st.sidebar.button(
    "Mostrar vista general",
    use_container_width=True
):

    st.session_state.cuenca_activa = None
    st.session_state.estacion_activa = None
    st.session_state.ultimo_clic = None
    st.rerun()

if st.sidebar.button(
    "Recargar archivos",
    use_container_width=True
):

    st.cache_data.clear()
    st.session_state.cuenca_activa = None
    st.session_state.estacion_activa = None
    st.session_state.ultimo_clic = None
    st.rerun()


# ============================================================
# 7. CARGAR DATOS
# ============================================================

with st.spinner("Leyendo capas geográficas..."):

    capas_sudamerica, e1 = cargar_carpeta(
        "sudamerica"
    )

    capas_subcuencas, e2 = cargar_carpeta(
        "subcuencas"
    )

    capas_rios, e3 = cargar_carpeta(
        "rios"
    )

    capas_puntos, e4 = cargar_carpeta(
        "puntos"
    )

errores = e1 + e2 + e3 + e4


# ============================================================
# 8. INDICADORES
# ============================================================

total_estaciones = sum(
    len(gdf)
    for _, gdf in capas_puntos
)

c1, c2, c3 = st.columns(3)

c1.metric(
    "Estaciones",
    total_estaciones
)

c2.metric(
    "Subcuencas",
    len(capas_subcuencas)
)

c3.metric(
    "Capas de ríos",
    len(capas_rios)
)


# ============================================================
# 9. MAPA
# ============================================================

seleccion = st.session_state.cuenca_activa

poligono_activo = obtener_poligono(
    seleccion,
    capas_subcuencas
)

capas_todas = (
    capas_sudamerica
    + capas_subcuencas
    + capas_rios
    + capas_puntos
)

bounds_general = extension_general(
    capas_todas
)

mapa = folium.Map(
    location=[-5, -74],
    zoom_start=5,
    tiles=None,
    prefer_canvas=True,
    control_scale=True
)

folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satélite",
    overlay=False,
    show=ver_satelite,
    max_zoom=20
).add_to(mapa)

folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=not ver_satelite
).add_to(mapa)


# ============================================================
# 10. SUDAMÉRICA
# ============================================================

if ver_sudamerica:

    grupo = folium.FeatureGroup(
        name="Sudamérica",
        show=True
    )

    for nombre, gdf in capas_sudamerica:

        folium.GeoJson(
            gdf.to_json(drop_id=True),
            style_function=lambda f: {
                "color": "#697783",
                "weight": 1,
                "fillColor": "#B0BAC2",
                "fillOpacity": 0.04,
            },
        ).add_to(grupo)

    grupo.add_to(mapa)


# ============================================================
# 11. SUBCUENCAS ATENUADAS
# UNA CAPA POR ARCHIVO, NO POR GEOMETRÍA
# ============================================================

if ver_subcuencas:

    grupo_cuencas = folium.FeatureGroup(
        name="Subcuencas",
        show=True
    )

    for nombre, gdf in capas_subcuencas:

        color = color_cuenca(nombre)

        # Solo geometría para el mapa general.
        geojson = gdf[
            [gdf.geometry.name]
        ].to_json(drop_id=True)

        folium.GeoJson(
            geojson,
            style_function=lambda f, c=color: {
                "color": c,
                "weight": 0.8,
                "opacity": 0.55 if seleccion is None else 0.22,
                "fillColor": c,
                "fillOpacity": 0.10 if seleccion is None else 0.025,
            },
            tooltip=nombre,
        ).add_to(grupo_cuencas)

    grupo_cuencas.add_to(mapa)


# ============================================================
# 12. RÍOS GENERALES ATENUADOS
# ============================================================

if ver_rios:

    grupo_rios = folium.FeatureGroup(
        name="Ríos",
        show=True
    )

    for nombre, gdf in capas_rios:

        geojson = gdf[
            [gdf.geometry.name]
        ].to_json(drop_id=True)

        folium.GeoJson(
            geojson,
            style_function=lambda f: {
                "color": COLOR_RIO_NORMAL,
                "weight": 1.2,
                "opacity": 0.48 if seleccion is None else 0.14,
            },
            tooltip=nombre,
        ).add_to(grupo_rios)

    grupo_rios.add_to(mapa)


# ============================================================
# 13. CUENCA SELECCIONADA
# ============================================================

if poligono_activo is not None:

    grupo_activo = folium.FeatureGroup(
        name="Cuenca seleccionada",
        show=True
    )

    folium.GeoJson(
        {
            "type": "Feature",
            "geometry": poligono_activo.__geo_interface__,
            "properties": {
                "Codigo": seleccion[0]
            }
        },
        style_function=lambda f: {
            "color": COLOR_CUENCA_ACTIVA,
            "weight": 3.5,
            "opacity": 1,
            "fillColor": COLOR_CUENCA_ACTIVA,
            "fillOpacity": 0.35,
        },
        tooltip=f"Subcuenca: {seleccion[0]}",
    ).add_to(grupo_activo)

    grupo_activo.add_to(mapa)


# ============================================================
# 14. RÍOS DE LA CUENCA SELECCIONADA
# ============================================================

if (
    ver_rios
    and poligono_activo is not None
):

    grupo_rios_activos = folium.FeatureGroup(
        name="Ríos de la cuenca seleccionada",
        show=True
    )

    for nombre, gdf in capas_rios:

        try:

            mascara = gdf.geometry.intersects(
                poligono_activo
            )

            rios_intersectados = gdf.loc[
                mascara
            ].copy()

            if rios_intersectados.empty:
                continue

            # Mostrar solamente los tramos dentro
            # de la cuenca seleccionada.
            rios_intersectados.geometry = (
                rios_intersectados.geometry.intersection(
                    poligono_activo
                )
            )

            rios_intersectados = rios_intersectados[
                ~rios_intersectados.geometry.is_empty
            ]

            if rios_intersectados.empty:
                continue

            geojson = rios_intersectados[
                [rios_intersectados.geometry.name]
            ].to_json(drop_id=True)

            folium.GeoJson(
                geojson,
                style_function=lambda f: {
                    "color": COLOR_RIO_ACTIVO,
                    "weight": 3,
                    "opacity": 1,
                },
                tooltip=nombre,
            ).add_to(grupo_rios_activos)

        except Exception:
            continue

    grupo_rios_activos.add_to(mapa)


# ============================================================
# 15. ESTACIONES
# ============================================================

if ver_puntos:

    grupo_estaciones = folium.FeatureGroup(
        name="Estaciones hidrológicas",
        show=True
    )

    for nombre, gdf in capas_puntos:

        for indice, fila in gdf.iterrows():

            geom = fila.geometry

            if geom.geom_type != "Point":
                continue

            activa = (
                st.session_state.estacion_activa
                == (nombre, int(indice))
            )

            # Nombre de la estación a partir de atributos.
            nombre_estacion = nombre

            for campo in [
                "Estacion", "ESTACION", "estacion",
                "Nombre", "NOMBRE", "nombre",
                "Codigo", "CODIGO", "codigo"
            ]:

                if campo in gdf.columns:

                    valor = fila[campo]

                    if str(valor).strip():
                        nombre_estacion = str(valor)
                        break

            folium.CircleMarker(
                location=[
                    geom.y,
                    geom.x
                ],
                radius=7 if activa else 4,
                color="#FFFFFF",
                weight=1.5,
                fill=True,
                fill_color=(
                    COLOR_ESTACION_ACTIVA
                    if activa
                    else COLOR_ESTACION
                ),
                fill_opacity=1,
                tooltip=nombre_estacion,
            ).add_to(grupo_estaciones)

    grupo_estaciones.add_to(mapa)


# ============================================================
# 16. EXTENSIÓN DEL MAPA
# ============================================================

if poligono_activo is not None:

    bx1, by1, bx2, by2 = poligono_activo.bounds

    mapa.fit_bounds(
        [
            [by1, bx1],
            [by2, bx2]
        ],
        padding=(35, 35)
    )

else:

    mapa.fit_bounds(
        bounds_general,
        padding=(20, 20)
    )


# ============================================================
# 17. CONTROLES
# ============================================================

Fullscreen(
    position="topleft"
).add_to(mapa)

folium.LayerControl(
    collapsed=True
).add_to(mapa)


# ============================================================
# 18. MOSTRAR MAPA
# ============================================================

st.subheader("Visor geoespacial")

st.caption(
    "Haz clic en una estación roja para resaltar "
    "su subcuenca y los ríos correspondientes."
)

resultado = st_folium(
    mapa,
    use_container_width=True,
    height=720,
    returned_objects=[
        "last_object_clicked",
        "last_clicked",
    ],
    key="mapa_bid"
)


# ============================================================
# 19. PROCESAR SELECCIÓN
# ============================================================

if resultado:

    clic = resultado.get("last_object_clicked")

    if clic is not None:

        lat = clic.get("lat")
        lon = clic.get("lng")

        if lat is not None and lon is not None:

            identificador_clic = (
                round(lat, 7),
                round(lon, 7)
            )

            if (
                identificador_clic
                != st.session_state.ultimo_clic
            ):

                st.session_state.ultimo_clic = (
                    identificador_clic
                )

                estacion = buscar_estacion(
                    lat,
                    lon,
                    capas_puntos
                )

                if estacion is not None:

                    nombre_estacion, indice, geom = estacion

                    cuenca = buscar_cuenca(
                        geom.y,
                        geom.x,
                        capas_subcuencas
                    )

                    st.session_state.estacion_activa = (
                        nombre_estacion,
                        indice
                    )

                    st.session_state.cuenca_activa = cuenca

                    st.rerun()


# ============================================================
# 20. INFORMACIÓN DE LA SELECCIÓN
# ============================================================

if st.session_state.cuenca_activa is not None:

    nombre_cuenca = (
        st.session_state.cuenca_activa[0]
    )

    st.success(
        f"Subcuenca seleccionada: {nombre_cuenca}"
    )

elif st.session_state.estacion_activa is not None:

    st.warning(
        "La estación seleccionada no pudo asociarse "
        "con una subcuenca."
    )


# ============================================================
# 21. DIAGNÓSTICO
# ============================================================

if errores:

    with st.expander(
        f"Errores de lectura ({len(errores)})"
    ):

        for error in errores:
            st.write(error)


# ============================================================
# 22. PIE DE PÁGINA
# ============================================================

st.caption(
    "Visor Hidrológico BID | Ecuador · Perú · Bolivia"
)

