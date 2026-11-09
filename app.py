
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

DIR_PUNTOS = ROOT / "puntos"
DIR_RIOS = ROOT / "rios"
DIR_SUBCUENCAS = ROOT / "subcuencas"
DIR_SUDAMERICA = ROOT / "sudamerica"

COLOR_RIO = "#8CB8CC"
COLOR_RIO_SELECCION = "#00A6D6"
COLOR_SELECCION = "#FFD21F"
COLOR_PUNTO = "#D94A45"

PALETA = [
    "#A6B98A", "#9C91B8", "#C3A17D", "#78A6C8",
    "#B58A9A", "#A6AD78", "#8E9DB5", "#C1A477",
    "#7FA69A", "#AA8F78", "#8F9FBA", "#B28DAD",
    "#91A77B", "#C19B8B", "#7899A8", "#A89C72",
    "#A1A1A1", "#8CA6A0", "#B5A08A", "#929FBD",
]


# ============================================================
# 2. ENCABEZADO NATIVO DE STREAMLIT
# IMPORTANTE: NO SE UTILIZA HTML
# ============================================================

st.title(
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

st.caption(
    "Ecuador · Perú · Bolivia | Cuencas, ríos y estaciones hidrológicas"
)

st.divider()


# ============================================================
# 3. FUNCIONES DE ARCHIVOS
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


def nombre_relativo(archivo, carpeta):

    try:
        return archivo.relative_to(carpeta).with_suffix("").as_posix()
    except Exception:
        return archivo.stem


def color_estable(nombre):

    numero = int(
        hashlib.md5(
            nombre.encode("utf-8")
        ).hexdigest()[:8],
        16
    )

    return PALETA[numero % len(PALETA)]


# ============================================================
# 4. LECTURA CON CACHÉ
# ============================================================

@st.cache_data(show_spinner=False, max_entries=150)
def leer_shp(ruta, modificacion):

    return gpd.read_file(
        ruta,
        engine="pyogrio"
    )


@st.cache_data(show_spinner=False, max_entries=250)
def leer_gpkg(ruta, capa, modificacion):

    return gpd.read_file(
        ruta,
        layer=capa,
        engine="pyogrio"
    )


def preparar_gdf(gdf, tipo):

    if gdf is None or gdf.empty:
        raise ValueError("Archivo vacío.")

    if gdf.crs is None:
        raise ValueError("No tiene CRS definido.")

    gdf = gdf[
        gdf.geometry.notna()
    ].copy()

    gdf = gdf[
        ~gdf.geometry.is_empty
    ].copy()

    if gdf.empty:
        raise ValueError("No contiene geometrías válidas.")

    if gdf.crs.to_epsg() != 4326:

        gdf = gdf.to_crs(
            epsg=4326
        )

    tolerancias = {
        "puntos": 0,
        "rios": 0.00010,
        "subcuencas": 0.00020,
        "sudamerica": 0.00050,
    }

    tolerancia = tolerancias.get(tipo, 0)

    if tolerancia:

        gdf.geometry = gdf.geometry.simplify(
            tolerance=tolerancia,
            preserve_topology=True
        )

    return gdf.reset_index(drop=True)


def cargar_archivo(archivo, carpeta, tipo):

    nombre = nombre_relativo(
        archivo,
        carpeta
    )

    mtime = archivo.stat().st_mtime

    resultados = []

    if archivo.suffix.lower() == ".shp":

        gdf = leer_shp(
            str(archivo),
            mtime
        )

        gdf = preparar_gdf(
            gdf,
            tipo
        )

        resultados.append(
            (nombre, gdf)
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

        for capa in nombres:

            gdf = leer_gpkg(
                str(archivo),
                capa,
                mtime
            )

            gdf = preparar_gdf(
                gdf,
                tipo
            )

            nombre_capa = (
                nombre if len(nombres) == 1
                else f"{nombre} - {capa}"
            )

            resultados.append(
                (nombre_capa, gdf)
            )

    return resultados


def cargar_carpeta(carpeta, tipo):

    capas = []
    errores = []

    for archivo in buscar_archivos(carpeta):

        try:

            capas.extend(
                cargar_archivo(
                    archivo,
                    carpeta,
                    tipo
                )
            )

        except Exception as error:

            errores.append(
                f"{archivo.name}: {error}"
            )

    return capas, errores


# ============================================================
# 5. CARGAR LAS CUATRO CARPETAS
# ============================================================

with st.spinner("Cargando información geográfica..."):

    capas_sudamerica, errores_sudamerica = cargar_carpeta(
        DIR_SUDAMERICA,
        "sudamerica"
    )

    capas_puntos, errores_puntos = cargar_carpeta(
        DIR_PUNTOS,
        "puntos"
    )

    capas_rios, errores_rios = cargar_carpeta(
        DIR_RIOS,
        "rios"
    )

    capas_subcuencas, errores_subcuencas = cargar_carpeta(
        DIR_SUBCUENCAS,
        "subcuencas"
    )

errores = (
    errores_sudamerica
    + errores_puntos
    + errores_rios
    + errores_subcuencas
)


# ============================================================
# 6. PANEL LATERAL
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
    f"Sudamérica: {len(buscar_archivos(DIR_SUDAMERICA))}"
)

st.sidebar.write(
    f"Puntos: {len(buscar_archivos(DIR_PUNTOS))}"
)

st.sidebar.write(
    f"Ríos: {len(buscar_archivos(DIR_RIOS))}"
)

st.sidebar.write(
    f"Subcuencas: {len(buscar_archivos(DIR_SUBCUENCAS))}"
)

if st.sidebar.button(
    "Recargar archivos",
    use_container_width=True
):

    st.cache_data.clear()

    for key in [
        "subcuenca_seleccionada",
        "estacion_seleccionada",
        "ultimo_clic"
    ]:
        st.session_state.pop(key, None)

    st.rerun()


# ============================================================
# 7. ESTADO DE SELECCIÓN
# ============================================================

if "subcuenca_seleccionada" not in st.session_state:
    st.session_state.subcuenca_seleccionada = None

if "estacion_seleccionada" not in st.session_state:
    st.session_state.estacion_seleccionada = None

if "ultimo_clic" not in st.session_state:
    st.session_state.ultimo_clic = None


# ============================================================
# 8. IDENTIFICAR SUBCUENCA
# ============================================================

def buscar_subcuenca(lat, lon):

    punto = Point(lon, lat)

    for nombre, gdf in capas_subcuencas:

        for indice, geometria in enumerate(gdf.geometry):

            try:

                if geometria.covers(punto):

                    return nombre, indice

            except Exception:
                continue

    # Si no está dentro, buscar la más cercana.
    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_subcuencas:

        for indice, geometria in enumerate(gdf.geometry):

            try:

                distancia = geometria.distance(punto)

                if distancia < distancia_minima:

                    distancia_minima = distancia

                    mejor = (
                        nombre,
                        indice
                    )

            except Exception:
                continue

    # Máximo aproximado de 5 km en coordenadas geográficas.
    if distancia_minima > 0.05:
        return None

    return mejor


def buscar_estacion(lat, lon):

    punto_clic = Point(lon, lat)

    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_puntos:

        for indice, geometria in enumerate(gdf.geometry):

            if geometria.geom_type != "Point":
                continue

            distancia = geometria.distance(
                punto_clic
            )

            if distancia < distancia_minima:

                distancia_minima = distancia

                mejor = (
                    nombre,
                    indice,
                    geometria
                )

    if mejor is None or distancia_minima > 0.02:
        return None

    return mejor


# ============================================================
# 9. EXTENSIÓN GENERAL
# ============================================================

todas_las_capas = (
    capas_sudamerica
    + capas_subcuencas
    + capas_rios
    + capas_puntos
)

limites = [
    gdf.total_bounds
    for _, gdf in todas_las_capas
    if not gdf.empty
]

if limites:

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    centro = [
        (ymin + ymax) / 2,
        (xmin + xmax) / 2
    ]

else:

    xmin, ymin, xmax, ymax = -82, -20, -55, 5
    centro = [-4, -75]


# ============================================================
# 10. CREAR MAPA
# ============================================================

mapa = folium.Map(
    location=centro,
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True,
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
# 11. SUDAMÉRICA
# ============================================================

if ver_sudamerica:

    for nombre, gdf in capas_sudamerica:

        folium.GeoJson(
            gdf.to_json(drop_id=True),
            name=f"Sudamérica - {nombre}",
            style_function=lambda feature: {
                "color": "#59636E",
                "weight": 1,
                "fillColor": "#B9C2CA",
                "fillOpacity": 0.08,
            },
            show=True
        ).add_to(mapa)


# ============================================================
# 12. SUBCUENCAS
# ============================================================

seleccion = st.session_state.subcuenca_seleccionada

if ver_subcuencas:

    for nombre, gdf in capas_subcuencas:

        color_normal = color_estable(nombre)

        for indice, fila in gdf.iterrows():

            geometria = fila.geometry

            seleccionada = (
                seleccion is not None
                and seleccion == (nombre, indice)
            )

            if seleccionada:

                color = COLOR_SELECCION
                opacidad = 0.55
                grosor = 3

            else:

                color = color_normal
                opacidad = 0.045 if seleccion else 0.13
                grosor = 0.8 if seleccion else 1

            feature = {
                "type": "Feature",
                "geometry": geometria.__geo_interface__,
                "properties": {
                    "Codigo": nombre
                }
            }

            folium.GeoJson(
                feature,
                name=nombre,
                style_function=lambda f, c=color, o=opacidad, w=grosor: {
                    "color": c,
                    "weight": w,
                    "fillColor": c,
                    "fillOpacity": o,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["Codigo"]
                ),
                show=True
            ).add_to(mapa)


# ============================================================
# 13. RÍOS
# ============================================================

if ver_rios:

    poligono_seleccionado = None

    if seleccion is not None:

        for nombre, gdf in capas_subcuencas:

            if nombre == seleccion[0]:

                poligono_seleccionado = (
                    gdf.geometry.iloc[seleccion[1]]
                )

                break

    for nombre, gdf in capas_rios:

        for _, fila in gdf.iterrows():

            geometria = fila.geometry

            es_rio_seleccionado = False

            if poligono_seleccionado is not None:

                try:

                    es_rio_seleccionado = (
                        geometria.intersects(
                            poligono_seleccionado
                        )
                    )

                except Exception:
                    pass

            if es_rio_seleccionado:

                color = COLOR_RIO_SELECCION
                grosor = 3
                opacidad = 1

            else:

                color = COLOR_RIO
                grosor = 1 if seleccion else 1.5
                opacidad = 0.13 if seleccion else 0.55

            folium.GeoJson(
                {
                    "type": "Feature",
                    "geometry": geometria.__geo_interface__,
                    "properties": {}
                },
                name=nombre,
                style_function=lambda f, c=color, w=grosor, o=opacidad: {
                    "color": c,
                    "weight": w,
                    "opacity": o,
                },
                show=True
            ).add_to(mapa)


# ============================================================
# 14. ESTACIONES
# ============================================================

if ver_puntos:

    for nombre, gdf in capas_puntos:

        for indice, fila in gdf.iterrows():

            geometria = fila.geometry

            if geometria.geom_type != "Point":
                continue

            estacion_sel = st.session_state.estacion_seleccionada

            es_seleccionado = (
                estacion_sel is not None
                and estacion_sel == (nombre, indice)
            )

            color = (
                "#FFD000"
                if es_seleccionado
                else COLOR_PUNTO
            )

            radio = (
                8
                if es_seleccionado
                else 4
            )

            folium.CircleMarker(
                location=[
                    geometria.y,
                    geometria.x
                ],
                radius=radio,
                color="#FFFFFF",
                weight=1,
                fill=True,
                fill_color=color,
                fill_opacity=1 if es_seleccionado else 0.85,
                tooltip=nombre,
                popup=nombre,
            ).add_to(mapa)


# ============================================================
# 15. ZOOM A LA SUBCUENCA SELECCIONADA
# ============================================================

if seleccion is not None:

    for nombre, gdf in capas_subcuencas:

        if nombre == seleccion[0]:

            geometria = gdf.geometry.iloc[
                seleccion[1]
            ]

            bx1, by1, bx2, by2 = geometria.bounds

            mapa.fit_bounds(
                [
                    [by1, bx1],
                    [by2, bx2]
                ],
                padding=(35, 35)
            )

            break

else:

    mapa.fit_bounds(
        [
            [ymin, xmin],
            [ymax, xmax]
        ],
        padding=(20, 20)
    )


# ============================================================
# 16. CONTROLES
# ============================================================

Fullscreen(
    position="topleft"
).add_to(mapa)

folium.LayerControl(
    collapsed=True
).add_to(mapa)


# ============================================================
# 17. VISUALIZAR MAPA
# ============================================================

st.subheader("Visor geoespacial")

resultado = st_folium(
    mapa,
    use_container_width=True,
    height=720,
    returned_objects=[
        "last_object_clicked",
        "last_object_clicked_count"
    ],
    key="visor_hidrologico_bid"
)


# ============================================================
# 18. PROCESAR CLIC SOBRE ESTACIÓN
# ============================================================

if resultado:

    clic = resultado.get(
        "last_object_clicked"
    )

    contador = resultado.get(
        "last_object_clicked_count"
    )

    if clic and contador is not None:

        if contador != st.session_state.ultimo_clic:

            st.session_state.ultimo_clic = contador

            lat = clic.get("lat")
            lon = clic.get("lng")

            if lat is not None and lon is not None:

                estacion = buscar_estacion(
                    lat,
                    lon
                )

                if estacion is not None:

                    nombre_estacion = estacion[0]
                    indice_estacion = estacion[1]
                    geometria = estacion[2]

                    nueva_subcuenca = buscar_subcuenca(
                        geometria.y,
                        geometria.x
                    )

                    st.session_state.estacion_seleccionada = (
                        nombre_estacion,
                        indice_estacion
                    )

                    st.session_state.subcuenca_seleccionada = (
                        nueva_subcuenca
                    )

                    st.rerun()


# ============================================================
# 19. INFORMACIÓN DE SELECCIÓN
# ============================================================

if st.session_state.subcuenca_seleccionada:

    nombre_subcuenca = (
        st.session_state.subcuenca_seleccionada[0]
    )

    st.info(
        f"Subcuenca seleccionada: {nombre_subcuenca}"
    )

if errores:

    with st.expander("Diagnóstico de archivos"):

        for error in errores:
            st.write(error)

