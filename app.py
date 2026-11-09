# -*- coding: utf-8 -*-

from pathlib import Path
import colorsys
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

COLOR_CUENCA_ACTIVA = "#FFC400"
COLOR_BORDE_ACTIVO = "#FFFFFF"
COLOR_RIO_ACTIVO = "#00BFFF"
COLOR_RIO_NORMAL = "#8FB9C9"
COLOR_ESTACION = "#D9534F"
COLOR_ESTACION_ACTIVA = "#FFD000"

CAMPOS_NOMBRE = [
    "Estacion", "ESTACION", "estacion",
    "Nombre", "NOMBRE", "nombre",
    "Codigo", "CODIGO", "codigo",
]

# Proyección de área equivalente para calcular superficies.
CRS_AREA = "EPSG:6933"


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


def color_por_indice(i, desplazamiento=0):
    """Color distinto por polígono (espaciado por proporción áurea)."""

    hue = ((i + desplazamiento) * 0.61803398875) % 1.0
    sat = 0.50 + 0.18 * ((i * 7) % 3) / 2
    val = 0.88 - 0.10 * ((i * 5) % 3) / 2

    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)

    return "#{:02X}{:02X}{:02X}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )


@st.cache_resource(show_spinner=False, max_entries=60)
def leer_archivo(ruta, capa, modificacion):

    if capa is None:
        return gpd.read_file(ruta, engine="pyogrio")

    return gpd.read_file(ruta, layer=capa, engine="pyogrio")


@st.cache_resource(show_spinner=False, max_entries=60)
def preparar_archivo(ruta, capa, modificacion, tipo):

    gdf = leer_archivo(ruta, capa, modificacion)

    if gdf.empty:
        return None

    if gdf.crs is None:
        raise ValueError("El archivo no tiene CRS.")

    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[~gdf.geometry.is_empty]

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

    gdf = gdf.copy()

    if tolerancia > 0:
        try:
            gdf.geometry = gdf.geometry.simplify(
                tolerance=tolerancia,
                preserve_topology=True
            )
        except Exception:
            pass

    geom_col = gdf.geometry.name

    atributos = [
        c for c in gdf.columns
        if c != geom_col
    ][:3]

    gdf = gdf[atributos + [geom_col]].copy()

    return gdf.reset_index(drop=True)


@st.cache_resource(show_spinner=False, max_entries=120)
def geojson_capa(tipo, nombre, _gdf):
    """GeoJSON (solo geometría) cacheado, coordenadas redondeadas.
    Para subcuencas añade una propiedad 'color' distinta por polígono."""

    geom_col = _gdf.geometry.name
    solo_geom = _gdf[[geom_col]].copy()

    try:
        solo_geom.geometry = solo_geom.geometry.set_precision(
            grid_size=0.00001
        )
        solo_geom = solo_geom[~solo_geom.geometry.is_empty]
    except Exception:
        pass

    if tipo == "subcuencas":

        desplazamiento = int(
            hashlib.md5(nombre.encode("utf-8")).hexdigest()[:4], 16
        ) % 997

        solo_geom = solo_geom.reset_index(drop=True)

        solo_geom["color"] = [
            color_por_indice(i, desplazamiento)
            for i in range(len(solo_geom))
        ]

    return solo_geom.to_json(drop_id=True)


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

                listado = pyogrio.list_layers(str(archivo))

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

                    if capa is not None and len(capas_internas) > 1:
                        nombre = f"{nombre_base} - {capa}"

                    capas.append((nombre, gdf))

                except Exception as e:
                    errores.append(f"{archivo.name} / {capa}: {e}")

        except Exception as e:
            errores.append(f"{archivo.name}: {e}")

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

    if distancia_minima > 0.02:
        return None

    return mejor


def buscar_cuenca(lat, lon, capas_subcuencas):

    punto = Point(lon, lat)

    candidatas = []

    for nombre, gdf in capas_subcuencas:

        try:

            mascara = gdf.geometry.covers(punto)

            if mascara.any():

                for indice in gdf.index[mascara]:

                    geom = gdf.geometry.loc[indice]

                    candidatas.append(
                        (geom.area, nombre, int(indice))
                    )

        except Exception:
            continue

    if candidatas:
        candidatas.sort(key=lambda x: x[0])
        return (candidatas[0][1], candidatas[0][2])

    mejor = None
    distancia_minima = float("inf")

    for nombre, gdf in capas_subcuencas:

        try:

            distancias = gdf.geometry.distance(punto)

            indice = distancias.idxmin()
            distancia = float(distancias.loc[indice])

            if distancia < distancia_minima:
                distancia_minima = distancia
                mejor = (nombre, int(indice))

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


def calcular_area_km2(poligono):
    """Área del polígono en km² usando proyección de área equivalente."""

    try:
        serie = gpd.GeoSeries([poligono], crs="EPSG:4326")
        return float(serie.to_crs(CRS_AREA).area.iloc[0]) / 1_000_000
    except Exception:
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
        return [[-20, -82], [5, -60]]

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    return [[ymin, xmin], [ymax, xmax]]


def columna_nombre(gdf):

    for campo in CAMPOS_NOMBRE:
        if campo in gdf.columns:
            return campo

    return None


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

ver_sudamerica = st.sidebar.checkbox("Sudamérica", value=True)
ver_subcuencas = st.sidebar.checkbox("Subcuencas", value=True)
ver_rios = st.sidebar.checkbox("Ríos", value=True)
ver_puntos = st.sidebar.checkbox("Estaciones hidrológicas", value=True)
ver_satelite = st.sidebar.checkbox("Google Satélite", value=True)

st.sidebar.divider()

if st.sidebar.button("Mostrar vista general", use_container_width=True):

    st.session_state.cuenca_activa = None
    st.session_state.estacion_activa = None
    st.session_state.ultimo_clic = None
    st.rerun()

if st.sidebar.button("Recargar archivos", use_container_width=True):

    st.cache_data.clear()
    st.cache_resource.clear()
    st.session_state.cuenca_activa = None
    st.session_state.estacion_activa = None
    st.session_state.ultimo_clic = None
    st.rerun()


# ============================================================
# 7. CARGAR DATOS
# ============================================================

with st.spinner("Leyendo capas geográficas..."):

    capas_sudamerica, e1 = cargar_carpeta("sudamerica")
    capas_subcuencas, e2 = cargar_carpeta("subcuencas")
    capas_rios, e3 = cargar_carpeta("rios")
    capas_puntos, e4 = cargar_carpeta("puntos")

errores = e1 + e2 + e3 + e4


# ============================================================
# 8. INDICADORES
# ============================================================

total_estaciones = sum(len(gdf) for _, gdf in capas_puntos)

c1, c2, c3 = st.columns(3)

c1.metric("Estaciones", total_estaciones)
c2.metric("Archivos de subcuencas", len(capas_subcuencas))
c3.metric("Capas de ríos", len(capas_rios))


# ============================================================
# 9. MAPA
# ============================================================

seleccion = st.session_state.cuenca_activa

poligono_activo = obtener_poligono(seleccion, capas_subcuencas)

area_activa_km2 = (
    calcular_area_km2(poligono_activo)
    if poligono_activo is not None
    else None
)

capas_todas = (
    capas_sudamerica
    + capas_subcuencas
    + capas_rios
    + capas_puntos
)

bounds_general = extension_general(capas_todas)

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

    grupo = folium.FeatureGroup(name="Sudamérica", show=True)

    for nombre, gdf in capas_sudamerica:

        folium.GeoJson(
            geojson_capa("sudamerica", nombre, gdf),
            style_function=lambda f: {
                "color": "#697783",
                "weight": 1,
                "fillColor": "#B0BAC2",
                "fillOpacity": 0.04,
            },
        ).add_to(grupo)

    grupo.add_to(mapa)


# ============================================================
# 11. SUBCUENCAS: UN COLOR DISTINTO POR POLÍGONO
# ============================================================

if ver_subcuencas:

    grupo_cuencas = folium.FeatureGroup(name="Subcuencas", show=True)

    for nombre, gdf in capas_subcuencas:

        folium.GeoJson(
            geojson_capa("subcuencas", nombre, gdf),
            style_function=lambda f: {
                "color": f["properties"].get("color", "#888888"),
                "weight": 1.0 if seleccion is None else 0.5,
                "opacity": 0.85 if seleccion is None else 0.20,
                "fillColor": f["properties"].get("color", "#888888"),
                "fillOpacity": 0.45 if seleccion is None else 0.05,
            },
        ).add_to(grupo_cuencas)

    grupo_cuencas.add_to(mapa)


# ============================================================
# 12. RÍOS GENERALES (ATENUADOS SI HAY SELECCIÓN)
# ============================================================

if ver_rios:

    grupo_rios = folium.FeatureGroup(name="Ríos", show=True)

    for nombre, gdf in capas_rios:

        folium.GeoJson(
            geojson_capa("rios", nombre, gdf),
            style_function=lambda f: {
                "color": COLOR_RIO_NORMAL,
                "weight": 1.2,
                "opacity": 0.55 if seleccion is None else 0.12,
            },
        ).add_to(grupo_rios)

    grupo_rios.add_to(mapa)


# ============================================================
# 13. CUENCA SELECCIONADA (RESALTADA + ÁREA)
# ============================================================

if poligono_activo is not None:

    grupo_activo = folium.FeatureGroup(
        name="Cuenca seleccionada",
        show=True
    )

    texto_area = (
        f"Área: {area_activa_km2:,.2f} km²"
        if area_activa_km2 is not None
        else "Área no disponible"
    )

    feature_activo = {
        "type": "Feature",
        "geometry": poligono_activo.__geo_interface__,
        "properties": {},
    }

    # Capa inferior: brillo/halo blanco.
    folium.GeoJson(
        feature_activo,
        style_function=lambda f: {
            "color": COLOR_BORDE_ACTIVO,
            "weight": 9,
            "opacity": 0.35,
            "fillOpacity": 0,
        },
    ).add_to(grupo_activo)

    # Capa superior: relleno dorado con borde blanco.
    folium.GeoJson(
        feature_activo,
        style_function=lambda f: {
            "color": COLOR_BORDE_ACTIVO,
            "weight": 3,
            "opacity": 1,
            "fillColor": COLOR_CUENCA_ACTIVA,
            "fillOpacity": 0.45,
        },
        tooltip=texto_area,
    ).add_to(grupo_activo)

    grupo_activo.add_to(mapa)


# ============================================================
# 14. RÍOS DE LA CUENCA SELECCIONADA
# ============================================================

if ver_rios and poligono_activo is not None:

    grupo_rios_activos = folium.FeatureGroup(
        name="Ríos de la cuenca seleccionada",
        show=True
    )

    for nombre, gdf in capas_rios:

        try:

            mascara = gdf.geometry.intersects(poligono_activo)

            rios_intersectados = gdf.loc[mascara].copy()

            if rios_intersectados.empty:
                continue

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

        campo_nombre = columna_nombre(gdf)

        for indice in range(len(gdf)):

            geom = gdf.geometry.iloc[indice]

            if geom.geom_type != "Point":
                continue

            activa = (
                st.session_state.estacion_activa
                == (nombre, int(indice))
            )

            nombre_estacion = nombre

            if campo_nombre is not None:

                valor = str(gdf[campo_nombre].iloc[indice]).strip()

                if valor and valor.lower() != "none":
                    nombre_estacion = valor

            folium.CircleMarker(
                location=[geom.y, geom.x],
                radius=8 if activa else 4,
                color="#FFFFFF",
                weight=2 if activa else 1.5,
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
        [[by1, bx1], [by2, bx2]],
        padding=(35, 35)
    )

else:

    mapa.fit_bounds(bounds_general, padding=(20, 20))


# ============================================================
# 17. CONTROLES
# ============================================================

Fullscreen(position="topleft").add_to(mapa)

folium.LayerControl(collapsed=True).add_to(mapa)


# ============================================================
# 18. MOSTRAR MAPA
# ============================================================

st.subheader("Visor geoespacial")

st.caption(
    "Haz clic en una estación roja para resaltar "
    "su subcuenca y ver su área."
)

resultado = st_folium(
    mapa,
    use_container_width=True,
    height=720,
    returned_objects=["last_object_clicked"],
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

            identificador_clic = (round(lat, 7), round(lon, 7))

            if identificador_clic != st.session_state.ultimo_clic:

                st.session_state.ultimo_clic = identificador_clic

                estacion = buscar_estacion(lat, lon, capas_puntos)

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
# 20. ÁREA DE LA SELECCIÓN
# ============================================================

if st.session_state.cuenca_activa is not None:

    if area_activa_km2 is not None:
        st.success(f"Área de la subcuenca: {area_activa_km2:,.2f} km²")
    else:
        st.warning("No se pudo calcular el área de la subcuenca.")

elif st.session_state.estacion_activa is not None:

    st.warning(
        "La estación seleccionada no pudo asociarse "
        "con una subcuenca."
    )


# ============================================================
# 21. DIAGNÓSTICO
# ============================================================

if errores:

    with st.expander(f"Errores de lectura ({len(errores)})"):

        for error in errores:
            st.write(error)


# ============================================================
# 22. PIE DE PÁGINA
# ============================================================

st.caption("Visor Hidrológico BID | Ecuador · Perú · Bolivia")
