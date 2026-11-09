# -*- coding: utf-8 -*-

from pathlib import Path
from io import BytesIO
import colorsys
import hashlib
import re
import unicodedata
import warnings

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import geopandas as gpd
import pyogrio
import folium
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

from shapely.geometry import Point
from folium.plugins import Fullscreen

warnings.filterwarnings("ignore")

# ============================================================
# 1. CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Visor Hidrológico BID",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parent

CARPETAS = {
    "puntos": ROOT / "puntos",
    "rios": ROOT / "rios",
    "subcuencas": ROOT / "subcuencas",
    "sudamerica": ROOT / "sudamerica",
}

PAISES_MAP = {
    "ECUADOR": "Ecuador",
    "PERU": "Perú",
    "BOLIVIA": "Bolivia",
}

PAISES_LISTA = ["Ecuador", "Perú", "Bolivia"]
SIN_PAIS = "Sin país asignado"

COLORES_PAIS = {
    "Ecuador": "#F7E3A1",
    "Perú": "#F4B9AC",
    "Bolivia": "#BFDDA6",
}

COLOR_CUENCA_ACTIVA = "#FFC400"
COLOR_BORDE_ACTIVO = "#FFFFFF"
COLOR_RIO_ACTIVO = "#00BFFF"
COLOR_ESTACION_ACTIVA = "#FFD000"

CANDIDATOS_NOMBRE = [
    "ESTACION", "NOMBRE", "NAME", "NOMBREESTACION", "NOMESTACION",
    "NOMEST", "NOM", "STATION", "ESTNOMBRE",
]

CANDIDATOS_CODIGO = [
    "CODIGO", "COD", "CODE", "CODESTACION", "CODIGOESTACION",
    "CODEST", "IDESTACION", "ID", "IDE", "CODIGOEST",
]

CRS_AREA = "EPSG:6933"


# ============================================================
# 2. UTILIDADES
# ============================================================

def normalizar(texto):

    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))

    return t.upper().strip()


def normalizar_columna(texto):

    return re.sub(r"[^A-Z0-9]", "", normalizar(texto))


def pais_desde_texto(valor):

    n = normalizar(valor)

    for clave, nombre in PAISES_MAP.items():
        if clave in n:
            return nombre

    return None


def buscar_columna(gdf, candidatos):

    geom_col = gdf.geometry.name

    mapa = {
        normalizar_columna(c): c
        for c in gdf.columns
        if c != geom_col
    }

    for cand in candidatos:
        if cand in mapa:
            return mapa[cand]

    return None


def limpiar_valor(valor):

    texto = str(valor).strip()

    if texto == "" or texto.lower() in ("none", "nan", "nat", "<na>"):
        return "S/D"

    return texto


def color_por_indice(i, desplazamiento=0):
    """Color distinto por polígono (espaciado por proporción áurea)."""

    hue = ((i + desplazamiento) * 0.61803398875) % 1.0
    sat = 0.50 + 0.18 * ((i * 7) % 3) / 2
    val = 0.88 - 0.10 * ((i * 5) % 3) / 2

    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)

    return "#{:02X}{:02X}{:02X}".format(
        int(r * 255), int(g * 255), int(b * 255)
    )


def firma(capas):

    return "|".join(f"{n}:{len(g)}" for n, g in capas)


# ============================================================
# 3. LECTURA DE ARCHIVOS
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

    # Puntos y Sudamérica conservan atributos (código, nombre, país).
    # Ríos y subcuencas solo geometría.
    if tipo in ("puntos", "sudamerica"):
        gdf = gdf.copy()
    else:
        gdf = gdf[[geom_col]].copy()

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
# 4. PAÍSES Y ESTACIONES
# ============================================================

def detectar_columna_pais(gdf):

    geom_col = gdf.geometry.name

    for c in gdf.columns:

        if c == geom_col:
            continue

        if pd.api.types.is_numeric_dtype(gdf[c]):
            continue

        try:
            valores = gdf[c].dropna().astype(str).unique()[:3000]
        except Exception:
            continue

        if any(pais_desde_texto(v) for v in valores):
            return c

    return None


@st.cache_resource(show_spinner=False, max_entries=4)
def construir_paises(clave, _capas_sud):
    """Une los polígonos de Ecuador, Perú y Bolivia (uno por país)."""

    partes = []

    for _, gdf in _capas_sud:

        col = detectar_columna_pais(gdf)

        if col is None:
            continue

        paises = gdf[col].map(pais_desde_texto)

        g = gpd.GeoDataFrame(
            {
                "pais": paises.values,
                "geometry": gdf.geometry.values,
            },
            geometry="geometry",
            crs="EPSG:4326",
        )

        g = g[g["pais"].notna()]

        if not g.empty:
            partes.append(g)

    if not partes:
        return gpd.GeoDataFrame(
            {"pais": [], "geometry": []},
            geometry="geometry",
            crs="EPSG:4326",
        )

    todo = gpd.GeoDataFrame(
        pd.concat(partes, ignore_index=True),
        geometry="geometry",
        crs="EPSG:4326",
    )

    try:
        todo["geometry"] = todo.geometry.buffer(0)
    except Exception:
        pass

    return todo.dissolve(by="pais", as_index=False)


def asignar_pais(geom, paises_gdf):

    if paises_gdf is None or paises_gdf.empty:
        return SIN_PAIS

    for _, fila in paises_gdf.iterrows():
        if fila.geometry.covers(geom):
            return fila["pais"]

    distancias = paises_gdf.geometry.distance(geom)
    idx = distancias.idxmin()

    # ~11 km de tolerancia para estaciones en el borde.
    if float(distancias.loc[idx]) <= 0.1:
        return paises_gdf.loc[idx, "pais"]

    return SIN_PAIS


@st.cache_resource(show_spinner=False, max_entries=4)
def construir_estaciones(clave, _capas_puntos, _paises):
    """Lista de estaciones con país, código y nombre."""

    estaciones = []

    for nombre_capa, gdf in _capas_puntos:

        col_nombre = buscar_columna(gdf, CANDIDATOS_NOMBRE)
        col_codigo = buscar_columna(gdf, CANDIDATOS_CODIGO)

        otras = [
            c for c in gdf.columns
            if c != gdf.geometry.name
            and c != col_codigo
        ]

        if col_nombre is None and otras:
            col_nombre = otras[0]

        for i in range(len(gdf)):

            geom = gdf.geometry.iloc[i]

            if geom.geom_type != "Point":
                continue

            nombre = (
                limpiar_valor(gdf[col_nombre].iloc[i])
                if col_nombre is not None
                else f"Estación {i + 1}"
            )

            codigo = (
                limpiar_valor(gdf[col_codigo].iloc[i])
                if col_codigo is not None
                else "S/D"
            )

            estaciones.append(
                {
                    "clave": f"{nombre_capa}#{i}",
                    "capa": nombre_capa,
                    "nombre": nombre,
                    "codigo": codigo,
                    "pais": asignar_pais(geom, _paises),
                    "lat": float(geom.y),
                    "lon": float(geom.x),
                }
            )

    return estaciones


# ============================================================
# 5. FUNCIONES GEOGRÁFICAS
# ============================================================

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

    try:
        serie = gpd.GeoSeries([poligono], crs="EPSG:4326")
        return float(serie.to_crs(CRS_AREA).area.iloc[0]) / 1_000_000
    except Exception:
        return None


def rios_de_cuenca(poligono, capas_rios):
    """Tramos de río dentro de la cuenca, como lista de GeoJSON."""

    resultado = []

    if poligono is None:
        return resultado

    for nombre, gdf in capas_rios:

        try:

            posiciones = gdf.sindex.query(
                poligono,
                predicate="intersects"
            )

            if len(posiciones) == 0:
                continue

            sel = gdf.iloc[posiciones].copy()

            sel.geometry = sel.geometry.intersection(poligono)

            sel = sel[~sel.geometry.is_empty]

            if sel.empty:
                continue

            resultado.append(
                sel[[sel.geometry.name]].to_json(drop_id=True)
            )

        except Exception:
            continue

    return resultado


def extension_general(capas):

    limites = []

    for _, gdf in capas:

        if not gdf.empty:

            try:
                limites.append(gdf.total_bounds)
            except Exception:
                pass

    if not limites:
        return None

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    return xmin, ymin, xmax, ymax


# ============================================================
# 6. MAPA GENERAL ESTÁTICO (IMAGEN)
# ============================================================

@st.cache_data(show_spinner=False, max_entries=2)
def mapa_estatico(
    clave,
    _capas_sud,
    _capas_sub,
    _capas_rios,
    _estaciones,
    _paises,
):

    fig, ax = plt.subplots(figsize=(9, 10))

    ax.set_facecolor("#D6E6F2")

    for _, gdf in _capas_sud:
        try:
            gdf.plot(
                ax=ax,
                facecolor="#F1F0EA",
                edgecolor="#A7A79F",
                linewidth=0.4,
            )
        except Exception:
            pass

    if _paises is not None and not _paises.empty:

        for _, fila in _paises.iterrows():

            try:
                gpd.GeoSeries(
                    [fila.geometry],
                    crs="EPSG:4326"
                ).plot(
                    ax=ax,
                    facecolor=COLORES_PAIS.get(fila["pais"], "#DDDDDD"),
                    edgecolor="#555555",
                    linewidth=0.9,
                )
            except Exception:
                pass

    for nombre, gdf in _capas_sub:

        try:

            desplazamiento = int(
                hashlib.md5(nombre.encode("utf-8")).hexdigest()[:4], 16
            ) % 997

            colores = [
                color_por_indice(i, desplazamiento)
                for i in range(len(gdf))
            ]

            gdf.plot(
                ax=ax,
                color=colores,
                edgecolor="#555555",
                linewidth=0.15,
                alpha=0.60,
            )

        except Exception:
            pass

    for _, gdf in _capas_rios:
        try:
            gdf.plot(ax=ax, color="#2E86C1", linewidth=0.35)
        except Exception:
            pass

    if _estaciones:
        ax.scatter(
            [e["lon"] for e in _estaciones],
            [e["lat"] for e in _estaciones],
            s=9,
            c="#D9534F",
            edgecolors="white",
            linewidths=0.4,
            zorder=5,
        )

    if _paises is not None and not _paises.empty:

        for _, fila in _paises.iterrows():

            try:
                p = fila.geometry.representative_point()

                ax.annotate(
                    fila["pais"].upper(),
                    (p.x, p.y),
                    ha="center",
                    va="center",
                    fontsize=11,
                    fontweight="bold",
                    color="#2B2B2B",
                    alpha=0.85,
                    zorder=6,
                )
            except Exception:
                pass

    try:

        if _paises is not None and not _paises.empty:
            xmin, ymin, xmax, ymax = _paises.total_bounds
        else:
            xmin, ymin, xmax, ymax = extension_general(
                list(_capas_sud) + list(_capas_sub)
            )

        margen = 1.5

        ax.set_xlim(xmin - margen, xmax + margen)
        ax.set_ylim(ymin - margen, ymax + margen)

    except Exception:
        pass

    ax.set_aspect("equal")

    ax.grid(True, color="#B9C7D3", linewidth=0.4, linestyle="--")
    ax.tick_params(labelsize=7)
    ax.set_xlabel("Longitud", fontsize=8)
    ax.set_ylabel("Latitud", fontsize=8)

    ax.set_title(
        "Cuencas Andino-Amazónicas de Ecuador, Perú y Bolivia",
        fontsize=12,
        fontweight="bold",
    )

    leyenda = [
        Patch(facecolor=COLORES_PAIS["Ecuador"], edgecolor="#555", label="Ecuador"),
        Patch(facecolor=COLORES_PAIS["Perú"], edgecolor="#555", label="Perú"),
        Patch(facecolor=COLORES_PAIS["Bolivia"], edgecolor="#555", label="Bolivia"),
        Patch(facecolor="#C9B6D9", edgecolor="#555", alpha=0.7,
              label="Subcuencas (color por polígono)"),
        Line2D([0], [0], color="#2E86C1", linewidth=1.2, label="Ríos"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#D9534F",
               markeredgecolor="white", markersize=7, label="Estaciones"),
    ]

    ax.legend(
        handles=leyenda,
        loc="lower left",
        fontsize=7,
        framealpha=0.92,
    )

    buffer = BytesIO()

    fig.savefig(buffer, format="png", dpi=140, bbox_inches="tight")

    plt.close(fig)

    return buffer.getvalue()


# ============================================================
# 7. ENCABEZADO Y PANEL LATERAL
# ============================================================

st.title(
    "Modelamiento Hidrológico de las Cuencas "
    "Andino-Amazónicas de Ecuador, Perú y Bolivia"
)

st.caption(
    "Ecuador · Perú · Bolivia | "
    "Estaciones, subcuencas y red hidrográfica"
)

st.sidebar.title("Opciones")

ver_satelite = st.sidebar.checkbox(
    "Google Satélite en el mapa de cuenca",
    value=True
)

if st.sidebar.button("Recargar archivos", use_container_width=True):

    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# ============================================================
# 8. CARGAR DATOS
# ============================================================

with st.spinner("Leyendo capas geográficas..."):

    capas_sudamerica, e1 = cargar_carpeta("sudamerica")
    capas_subcuencas, e2 = cargar_carpeta("subcuencas")
    capas_rios, e3 = cargar_carpeta("rios")
    capas_puntos, e4 = cargar_carpeta("puntos")

errores = e1 + e2 + e3 + e4

clave_sud = firma(capas_sudamerica)
clave_sub = firma(capas_subcuencas)
clave_rios = firma(capas_rios)
clave_pts = firma(capas_puntos)

paises_gdf = construir_paises(clave_sud, capas_sudamerica)

estaciones = construir_estaciones(
    clave_pts + "||" + clave_sud,
    capas_puntos,
    paises_gdf
)

estaciones_por_clave = {e["clave"]: e for e in estaciones}


# ============================================================
# 9. INDICADORES
# ============================================================

conteo = {p: 0 for p in PAISES_LISTA}
conteo[SIN_PAIS] = 0

for e in estaciones:
    conteo[e["pais"]] = conteo.get(e["pais"], 0) + 1

m1, m2, m3, m4 = st.columns(4)

m1.metric("Estaciones totales", len(estaciones))
m2.metric("Ecuador", conteo["Ecuador"])
m3.metric("Perú", conteo["Perú"])
m4.metric("Bolivia", conteo["Bolivia"])

if paises_gdf.empty:
    st.warning(
        "No se pudo identificar la columna de países en el shape de "
        "Sudamérica. Revisa que la carpeta 'sudamerica' tenga una "
        "columna con los nombres de los países."
    )


# ============================================================
# 10. MAPA GENERAL (ESTÁTICO)
# ============================================================

st.subheader("Mapa general")

with st.spinner("Generando mapa general..."):

    imagen = mapa_estatico(
        clave_sud + "||" + clave_sub + "||" + clave_rios + "||" + clave_pts,
        capas_sudamerica,
        capas_subcuencas,
        capas_rios,
        estaciones,
        paises_gdf,
    )

st.image(imagen, use_container_width=True)


# ============================================================
# 11. SELECCIÓN DE PAÍS Y ESTACIÓN
# ============================================================

st.divider()

st.subheader("Explorar cuenca por estación")

opciones_pais = list(PAISES_LISTA)

if conteo.get(SIN_PAIS, 0) > 0:
    opciones_pais.append(SIN_PAIS)

col_a, col_b = st.columns(2)

with col_a:

    pais_sel = st.selectbox(
        "1. Selecciona el país",
        opciones_pais,
        index=None,
        placeholder="Ecuador, Perú o Bolivia",
        key="pais_sel",
    )

estacion_sel = None

with col_b:

    if pais_sel is None:

        st.selectbox(
            "2. Selecciona la estación",
            [],
            index=None,
            placeholder="Primero elige un país",
            disabled=True,
            key="estacion_vacia",
        )

    else:

        lista = sorted(
            [e for e in estaciones if e["pais"] == pais_sel],
            key=lambda e: e["nombre"].lower()
        )

        claves = [e["clave"] for e in lista]

        estacion_sel = st.selectbox(
            f"2. Selecciona la estación ({len(lista)} en {pais_sel})",
            claves,
            index=None,
            placeholder="Elige una estación",
            format_func=lambda k: (
                f"{estaciones_por_clave[k]['codigo']} — "
                f"{estaciones_por_clave[k]['nombre']}"
            ),
            key=f"estacion_{pais_sel}",
        )

if pais_sel is None:
    st.info("Selecciona un país para ver sus estaciones.")

elif estacion_sel is None:
    st.info("Selecciona una estación para cargar su cuenca.")


# ============================================================
# 12. CUENCA DE LA ESTACIÓN: MAPA (IZQ.) + CARACTERÍSTICAS (DER.)
# ============================================================

if estacion_sel is not None:

    try:

        est = estaciones_por_clave[estacion_sel]

        pasos = []

        pasos.append(
            f"Estación: {est['codigo']} — {est['nombre']} "
            f"({est['lat']:.5f}, {est['lon']:.5f})"
        )

        # --- Buscar subcuenca ---
        cuenca = buscar_cuenca(
            est["lat"],
            est["lon"],
            capas_subcuencas
        )

        poligono = obtener_poligono(cuenca, capas_subcuencas)

        if poligono is not None:
            pasos.append(f"Subcuenca encontrada en: {cuenca[0]} (fila {cuenca[1]})")
        else:
            pasos.append("No se encontró subcuenca cercana a la estación.")

        # --- Área ---
        area_km2 = (
            calcular_area_km2(poligono)
            if poligono is not None
            else None
        )

        # --- Ríos de la cuenca ---
        lista_rios = []

        if poligono is not None:
            lista_rios = rios_de_cuenca(poligono, capas_rios)

        pasos.append(f"Capas de ríos con tramos en la cuenca: {len(lista_rios)}")

        col_mapa, col_info = st.columns([3, 2])

        # ---------------- MAPA ----------------

        with col_mapa:

            mapa = folium.Map(
                location=[est["lat"], est["lon"]],
                zoom_start=10,
                tiles=None,
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

            if poligono is not None:

                texto_area = (
                    f"Área: {area_km2:,.2f} km²"
                    if area_km2 is not None
                    else "Cuenca"
                )

                feature = {
                    "type": "Feature",
                    "geometry": poligono.__geo_interface__,
                    "properties": {},
                }

                grupo_cuenca = folium.FeatureGroup(
                    name="Cuenca",
                    show=True
                )

                # Halo blanco.
                folium.GeoJson(
                    feature,
                    style_function=lambda f: {
                        "color": COLOR_BORDE_ACTIVO,
                        "weight": 9,
                        "opacity": 0.35,
                        "fillOpacity": 0,
                    },
                ).add_to(grupo_cuenca)

                # Relleno dorado.
                folium.GeoJson(
                    feature,
                    style_function=lambda f: {
                        "color": COLOR_BORDE_ACTIVO,
                        "weight": 3,
                        "opacity": 1,
                        "fillColor": COLOR_CUENCA_ACTIVA,
                        "fillOpacity": 0.40,
                    },
                    tooltip=texto_area,
                ).add_to(grupo_cuenca)

                grupo_cuenca.add_to(mapa)

                # Ríos dentro de la cuenca.
                grupo_rios = folium.FeatureGroup(
                    name="Ríos de la cuenca",
                    show=True
                )

                for geojson in lista_rios:

                    folium.GeoJson(
                        geojson,
                        style_function=lambda f: {
                            "color": COLOR_RIO_ACTIVO,
                            "weight": 3,
                            "opacity": 1,
                        },
                    ).add_to(grupo_rios)

                grupo_rios.add_to(mapa)

                bx1, by1, bx2, by2 = poligono.bounds

                mapa.fit_bounds(
                    [[by1, bx1], [by2, bx2]],
                    padding=(30, 30)
                )

            # Estación seleccionada.
            folium.CircleMarker(
                location=[est["lat"], est["lon"]],
                radius=8,
                color="#FFFFFF",
                weight=2,
                fill=True,
                fill_color=COLOR_ESTACION_ACTIVA,
                fill_opacity=1,
                tooltip=f"{est['codigo']} — {est['nombre']}",
            ).add_to(mapa)

            Fullscreen(position="topleft").add_to(mapa)

            folium.LayerControl(collapsed=True).add_to(mapa)

            # Se inserta como HTML (más estable que st_folium).
            html_mapa = mapa.get_root().render()

            components.html(html_mapa, height=620, scrolling=False)

        # ---------------- CARACTERÍSTICAS ----------------

        with col_info:

            st.markdown("#### Características de la cuenca")

            with st.container(border=True):

                st.markdown(f"**País**  \n{est['pais']}")
                st.markdown(f"**Código de la estación**  \n{est['codigo']}")
                st.markdown(f"**Nombre de la estación**  \n{est['nombre']}")

                if area_km2 is not None:
                    st.metric("Área de la cuenca", f"{area_km2:,.2f} km²")
                else:
                    st.warning(
                        "No se encontró una subcuenca para esta estación."
                    )

                st.caption(
                    f"Coordenadas: {est['lat']:.5f}, {est['lon']:.5f}"
                )

            with st.expander("Detalle del proceso"):

                for p in pasos:
                    st.write(p)

    except Exception as exc:

        st.error("Ocurrió un error al cargar la cuenca de esta estación:")
        st.exception(exc)


# ============================================================
# 13. DIAGNÓSTICO
# ============================================================

if errores:

    with st.expander(f"Errores de lectura ({len(errores)})"):

        for error in errores:
            st.write(error)

st.caption("Visor Hidrológico BID | Ecuador · Perú · Bolivia")
