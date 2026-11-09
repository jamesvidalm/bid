
# -*- coding: utf-8 -*-
"""
VISOR HIDROLÓGICO BID
Ecuador - Perú - Bolivia

Carpetas del repositorio:
    puntos/
    rios/
    subcuencas/
    sudamerica/

Comportamiento:
- Vista general con capas atenuadas.
- Clic en una estación para resaltar su subcuenca y sus ríos.
- Las demás capas permanecen atenuadas.
- Sin leyenda adicional.
"""

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

PALETA = [
    "#8DAA91", "#9C89B8", "#C49A6C", "#78A6C8",
    "#B58A9A", "#9DAA70", "#8E9DB5", "#C1A477",
    "#7FA69A", "#AA8F78", "#8F9FBA", "#B28DAD",
    "#91A77B", "#C19B8B", "#7899A8", "#A89C72",
]

COLOR_SELECCION = "#F2B705"
COLOR_RIO_GENERAL = "#A7C5D2"
COLOR_RIO_SELECCION = "#00A6D6"
COLOR_PUNTO = "#D94A45"
COLOR_PUNTO_SELECCION = "#FFD000"


# ============================================================
# 2. ENCABEZADO
# ============================================================

st.title(
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

st.caption(
    "Plataforma de visualización de cuencas, "
    "subcuencas, ríos y estaciones hidrológicas"
)


# ============================================================
# 3. FUNCIONES
# ============================================================

def buscar_archivos(carpeta):
    if not carpeta.exists():
        return []

    return sorted(
        [
            p for p in carpeta.rglob("*")
            if p.is_file()
            and p.suffix.lower() in [".shp", ".gpkg"]
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
        hashlib.md5(nombre.encode("utf-8")).hexdigest()[:8],
        16
    )
    return PALETA[numero % len(PALETA)]


@st.cache_data(show_spinner=False, max_entries=150)
def leer_shapefile(ruta, modificacion):
    return gpd.read_file(ruta, engine="pyogrio")


@st.cache_data(show_spinner=False, max_entries=250)
def leer_gpkg(ruta, capa, modificacion):
    return gpd.read_file(
        ruta,
        layer=capa,
        engine="pyogrio"
    )


def preparar_gdf(gdf, tipo):

    if gdf is None or gdf.empty:
        raise ValueError("Archivo sin registros.")

    if gdf.crs is None:
        raise ValueError("Archivo sin CRS.")

    gdf = gdf[
        gdf.geometry.notna()
    ].copy()

    gdf = gdf[
        ~gdf.geometry.is_empty
    ].copy()

    if gdf.empty:
        raise ValueError("Sin geometrías válidas.")

    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Simplificación según el tipo de geometría.
    tolerancias = {
        "puntos": 0,
        "rios": 0.00010,
        "subcuencas": 0.00020,
        "sudamerica": 0.00050,
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

    # Conservar solo algunos atributos para los popups.
    geometria = gdf.geometry.name

    atributos = [
        c for c in gdf.columns
        if c != geometria
    ][:5]

    gdf = gdf[atributos + [geometria]].copy()

    return gdf.reset_index(drop=True)


def cargar_archivo(archivo, carpeta, tipo):

    nombre = nombre_relativo(
        archivo,
        carpeta
    )

    mtime = archivo.stat().st_mtime

    resultados = []

    if archivo.suffix.lower() == ".shp":

        gdf = leer_shapefile(
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

            if len(nombres) == 1:
                nombre_capa = nombre
            else:
                nombre_capa = f"{nombre} - {capa}"

            resultados.append(
                (nombre_capa, gdf)
            )

    return resultados


def cargar_carpeta(carpeta, tipo):

    capas = []
    errores = []

    archivos = buscar_archivos(carpeta)

    for archivo in archivos:

        try:
            resultados = cargar_archivo(
                archivo,
                carpeta,
                tipo
            )

            capas.extend(resultados)

        except Exception as error:

            errores.append(
                f"{archivo.name}: {error}"
            )

    return capas, errores


def campos_popup(gdf):

    return [
        c for c in gdf.columns
        if c != gdf.geometry.name
    ][:5]


# ============================================================
# 4. CARGAR INFORMACIÓN GEOGRÁFICA
# ============================================================

with st.spinner("Cargando información geográfica..."):

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

    capas_sudamerica, errores_sudamerica = cargar_carpeta(
        DIR_SUDAMERICA,
        "sudamerica"
    )

errores = (
    errores_puntos
    + errores_rios
    + errores_subcuencas
    + errores_sudamerica
)


# ============================================================
# 5. PANEL LATERAL
# ============================================================

st.sidebar.title("Panel de visualización")

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

st.sidebar.write(
    f"Estaciones: {sum(len(g) for _, g in capas_puntos):,}"
)

st.sidebar.write(
    f"Capas de ríos: {len(capas_rios)}"
)

st.sidebar.write(
    f"Capas de subcuencas: {len(capas_subcuencas)}"
)

st.sidebar.write(
    f"Capas de Sudamérica: {len(capas_sudamerica)}"
)

if st.sidebar.button(
    "Recargar archivos",
    use_container_width=True
):
    st.cache_data.clear()
    st.session_state.pop("punto_seleccionado", None)
    st.session_state.pop("ultimo_clic", None)
    st.rerun()


# ============================================================
# 6. DETECTAR ESTACIÓN SELECCIONADA
# ============================================================

if "punto_seleccionado" not in st.session_state:
    st.session_state.punto_seleccionado = None

if "ultimo_clic" not in st.session_state:
    st.session_state.ultimo_clic = None


# ============================================================
# 7. IDENTIFICAR LA SUBCUENCA DEL PUNTO
# ============================================================

def buscar_subcuenca(lat, lon):

    punto = Point(lon, lat)

    seleccion = None
    distancia_minima = float("inf")

    # Primero busca el polígono que contiene el punto.
    for nombre, gdf in capas_subcuencas:

        for indice, geometria in enumerate(gdf.geometry):

            try:
                if geometria.covers(punto):
                    return nombre, indice
            except Exception:
                continue

    # Si no está dentro de un polígono,
    # selecciona la subcuenca más cercana.
    for nombre, gdf in capas_subcuencas:

        for indice, geometria in enumerate(gdf.geometry):

            try:
                distancia = geometria.distance(punto)

                if distancia < distancia_minima:
                    distancia_minima = distancia
                    seleccion = (nombre, indice)

            except Exception:
                continue

    # Evita seleccionar una subcuenca muy alejada.
    if distancia_minima > 0.05:
        return None

    return seleccion


def buscar_estacion_cercana(lat, lon):

    punto = Point(lon, lat)

    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_puntos:

        for indice, geometria in enumerate(gdf.geometry):

            try:
                distancia = geometria.distance(punto)

                if distancia < distancia_minima:
                    distancia_minima = distancia
                    mejor = (nombre, indice, geometria)

            except Exception:
                continue

    if mejor is None or distancia_minima > 0.02:
        return None

    return mejor


# ============================================================
# 8. CONSTRUIR MAPA
# ============================================================

todas_las_capas = (
    capas_sudamerica
    + capas_subcuencas
    + capas_rios
    + capas_puntos
)

if todas_las_capas:

    bounds = [
        gdf.total_bounds
        for _, gdf in todas_las_capas
    ]

    xmin = min(b[0] for b in bounds)
    ymin = min(b[1] for b in bounds)
    xmax = max(b[2] for b in bounds)
    ymax = max(b[3] for b in bounds)

    centro_general = [
        (ymin + ymax) / 2,
        (xmin + xmax) / 2
    ]

else:

    centro_general = [-4.0, -75.0]


seleccion = st.session_state.punto_seleccionado

mapa = folium.Map(
    location=centro_general,
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True,
)


# ============================================================
# 9. MAPAS BASE
# ============================================================

folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attr="Google Satellite",
    name="Google Satélite",
    overlay=False,
    show=ver_satelite,
    max_zoom=20,
).add_to(mapa)

folium.TileLayer(
    "OpenStreetMap",
    name="OpenStreetMap",
    overlay=False,
    show=not ver_satelite,
).add_to(mapa)


# ============================================================
# 10. SUDAMÉRICA
# ============================================================

if ver_sudamerica:

    for nombre, gdf in capas_sudamerica:

        folium.GeoJson(
            data=gdf.to_json(drop_id=True),
            name=f"Sudamérica - {nombre}",
            style_function=lambda feature: {
                "color": "#59636E",
                "weight": 1.2,
                "fillColor": "#B9C2CA",
                "fillOpacity": 0.10,
            },
            show=True,
        ).add_to(mapa)


# ============================================================
# 11. SUBCUENCAS
# ============================================================

if ver_subcuencas:

    for nombre, gdf in capas_subcuencas:

        for indice, fila in gdf.iterrows():

            geometria = fila.geometry

            es_seleccionada = (
                seleccion is not None
                and seleccion[0] == nombre
                and seleccion[1] == indice
            )

            if es_seleccionada:

                color = COLOR_SELECCION
                relleno = COLOR_SELECCION
                opacidad = 0.58
                grosor = 3.2

            else:

                color = color_estable(nombre)
                relleno = color
                opacidad = 0.055 if seleccion else 0.13
                grosor = 0.8 if seleccion else 1.0

            propiedades = fila.drop(
                labels=[gdf.geometry.name]
            ).to_dict()

            propiedades = {
                str(k): str(v)
                for k, v in propiedades.items()
            }

            feature = {
                "type": "Feature",
                "geometry": geometria.__geo_interface__,
                "properties": propiedades,
            }

            folium.GeoJson(
                data=feature,
                name=nombre,
                style_function=lambda f, c=color, o=opacidad, w=grosor, r=relleno: {
                    "color": c,
                    "weight": w,
                    "fillColor": r,
                    "fillOpacity": o,
                    "opacity": 0.95,
                },
                highlight_function=lambda f: {
                    "weight": 3.5,
                    "fillOpacity": 0.45,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=list(propiedades.keys())[:4]
                ) if propiedades else None,
                show=True,
            ).add_to(mapa)


# ============================================================
# 12. RÍOS
# ============================================================

if ver_rios:

    for nombre, gdf in capas_rios:

        for _, fila in gdf.iterrows():

            geometria = fila.geometry

            seleccionado = False

            if seleccion is not None:

                nombre_sub, indice_sub = seleccion

                try:
                    poligono = (
                        capas_subcuencas[
                            next(
                                i for i, x in enumerate(capas_subcuencas)
                                if x[0] == nombre_sub
                            )
                        ][1].geometry.iloc[indice_sub]
                    )

                    seleccionado = geometria.intersects(
                        poligono
                    )

                except Exception:
                    seleccionado = False

            if seleccionado:

                color = COLOR_RIO_SELECCION
                grosor = 3.0
                opacidad = 1.0

            else:

                color = COLOR_RIO_GENERAL
                grosor = 0.9 if seleccion else 1.5
                opacidad = 0.18 if seleccion else 0.55

            propiedades = fila.drop(
                labels=[gdf.geometry.name]
            ).to_dict()

            propiedades = {
                str(k): str(v)
                for k, v in propiedades.items()
            }

            feature = {
                "type": "Feature",
                "geometry": geometria.__geo_interface__,
                "properties": propiedades,
            }

            folium.GeoJson(
                data=feature,
                name=nombre,
                style_function=lambda f, c=color, w=grosor, o=opacidad: {
                    "color": c,
                    "weight": w,
                    "opacity": o,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=list(propiedades.keys())[:4]
                ) if propiedades else None,
                show=True,
            ).add_to(mapa)


# ============================================================
# 13. ESTACIONES HIDROLÓGICAS
# ============================================================

if ver_puntos:

    for nombre, gdf in capas_puntos:

        for indice, fila in gdf.iterrows():

            geometria = fila.geometry

            if geometria.geom_type != "Point":
                continue

            es_seleccionado = False

            if seleccion is not None:
                punto_sel = st.session_state.punto_seleccionado

                if punto_sel:
                    try:
                        es_seleccionado = (
                            abs(geometria.y - punto_sel["lat"]) < 0.00001
                            and
                            abs(geometria.x - punto_sel["lon"]) < 0.00001
                        )
                    except Exception:
                        pass

            if es_seleccionado:

                color = COLOR_PUNTO_SELECCION
                radio = 8
                opacidad = 1.0

            else:

                color = COLOR_PUNTO
                radio = 3.5
                opacidad = 0.45 if seleccion else 0.90

            propiedades = fila.drop(
                labels=[gdf.geometry.name]
            ).to_dict()

            propiedades = {
                str(k): str(v)
                for k, v in propiedades.items()
            }

            popup_html = "<br>".join(
                [
                    f"<b>{k}:</b> {v}"
                    for k, v in propiedades.items()
                ]
            )

            folium.CircleMarker(
                location=[
                    geometria.y,
                    geometria.x
                ],
                radius=radio,
                color="#FFFFFF",
                weight=1.2,
                fill=True,
                fill_color=color,
                fill_opacity=opacidad,
                tooltip=nombre,
                popup=folium.Popup(
                    popup_html or nombre,
                    max_width=350
                ),
            ).add_to(mapa)


# ============================================================
# 14. ENFOQUE DE LA SUBCUENCA SELECCIONADA
# ============================================================

if seleccion is not None:

    nombre_sub, indice_sub = seleccion

    for nombre, gdf in capas_subcuencas:

        if nombre == nombre_sub:

            geometria = gdf.geometry.iloc[indice_sub]

            xmin, ymin, xmax, ymax = geometria.bounds

            mapa.fit_bounds(
                [
                    [ymin, xmin],
                    [ymax, xmax]
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
# 15. CONTROLES
# ============================================================

Fullscreen(
    position="topleft"
).add_to(mapa)

folium.LayerControl(
    collapsed=True
).add_to(mapa)


# ============================================================
# 16. MOSTRAR MAPA Y CAPTURAR CLIC
# ============================================================

st.subheader("Visor geoespacial")

resultado = st_folium(
    mapa,
    use_container_width=True,
    height=720,
    returned_objects=[
        "last_object_clicked",
        "last_object_clicked_count",
    ],
    key="visor_bid",
)

# Detectar clic sobre una estación.
if resultado:

    clic = resultado.get("last_object_clicked")
    contador = resultado.get("last_object_clicked_count")

    if clic and contador is not None:

        if contador != st.session_state.ultimo_clic:

            st.session_state.ultimo_clic = contador

            lat = clic.get("lat")
            lon = clic.get("lng")

            if lat is not None and lon is not None:

                estacion = buscar_estacion_cercana(
                    lat,
                    lon
                )

                if estacion is not None:

                    punto_real = estacion[2]

                    lat_real = punto_real.y
                    lon_real = punto_real.x

                    nueva_seleccion = buscar_subcuenca(
                        lat_real,
                        lon_real
                    )

                    if nueva_seleccion is not None:

                        st.session_state.punto_seleccionado = {
                            "lat": lat_real,
                            "lon": lon_real,
                        }

                        st.session_state.subcuenca_seleccionada = (
                            nueva_seleccion
                        )

                        st.rerun()


# ============================================================
# 17. INFORMACIÓN DE SELECCIÓN
# ============================================================

if seleccion is not None:

    st.info(
        f"Subcuenca seleccionada: **{seleccion[0]}**. "
        "Se resaltan sus ríos y la estación seleccionada."
    )

if errores:

    with st.expander("Diagnóstico de archivos"):

        st.warning(
            f"Se encontraron {len(errores)} errores de lectura."
        )

        for error in errores:
            st.code(error)
