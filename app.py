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
    "rios_subcuencas": ROOT / "rios_subcuencas",
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
    "Ecuador": "#D35400",
    "Perú": "#1F618D",
    "Bolivia": "#148F77",
}

COLORES_CUENCAS = [
    "#7D3C98", "#B03A2E", "#2874A6", "#B9770E",
    "#117864", "#884EA0", "#CA6F1E", "#2E86C1",
]

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

# Distancia (grados) estación-borde para considerar que la estación
# está en la salida de la cuenca (~3 km).
TOL_SALIDA = 0.03

# Distancia (grados) para considerar válida una cuenca cercana (~2 km).
TOL_CERCANA = 0.02

# Si la estación está a más de ~5 km del borde, se avisa.
TOL_AVISO_KM = 5.0


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


@st.cache_resource(show_spinner=False, max_entries=12)
def leer_archivo(ruta, capa, modificacion):

    if capa is None:
        return gpd.read_file(ruta, engine="pyogrio")

    return gpd.read_file(ruta, layer=capa, engine="pyogrio")


@st.cache_resource(show_spinner=False, max_entries=12)
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
        "rios_subcuencas": 0.0001,
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
    """Une los polígonos de Ecuador y Perú (uno por país)."""

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

    todo = todo.dissolve(by="pais", as_index=False)

    # Conservar únicamente el componente continental principal de cada país.
    # Esto excluye Galápagos y otros polígonos insulares separados del continente.
    geometria_principal = []

    for geom in todo.geometry:
        if geom is None or geom.is_empty:
            geometria_principal.append(geom)
            continue

        if geom.geom_type == "Polygon":
            geometria_principal.append(geom)
            continue

        partes = [
            parte for parte in getattr(geom, "geoms", [])
            if parte.geom_type == "Polygon" and not parte.is_empty
        ]

        if partes:
            geometria_principal.append(max(partes, key=lambda parte: parte.area))
        else:
            geometria_principal.append(geom)

    todo = todo.copy()
    todo.geometry = geometria_principal

    return todo


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
# 5. ASOCIAR ESTACIÓN -> SUBCUENCA
# ============================================================

def nombre_corto(nombre_capa):
    """'carpeta/BID_033 - capa' -> 'BID_033'."""

    return nombre_capa.split("/")[-1].split(" - ")[0]


def clave_codigo(texto):

    return re.sub(r"[^A-Z0-9]", "", normalizar(texto))


def coincide_codigo(codigo, nombre_capa):
    """True si el código corresponde al nombre del archivo/capa
    (BID_033 <-> BID_033)."""

    c = clave_codigo(codigo)

    if not c or c == "SD":
        return False

    s = clave_codigo(nombre_corto(nombre_capa))

    if c == s:
        return True

    # Código completo dentro del nombre, sin pegarse a otros dígitos
    # (evita que BID_03 coincida con BID_033).
    completo = clave_codigo(nombre_capa)

    if re.search(rf"(?<![0-9]){re.escape(c)}(?![0-9])", completo):
        return True

    # Mismo prefijo y mismo número (BID_33 <-> BID_033).
    pc = re.match(r"^([A-Z]*)(\d+)$", c)
    ps = re.match(r"^([A-Z]*)(\d+)$", s)

    if pc and ps and pc.group(1) == ps.group(1):
        return int(pc.group(2)) == int(ps.group(2))

    return False


def cargar_archivos_por_codigo(tipo, codigo, es_rio=False):
    # Carga solo el archivo/capa asociado al código de estación seleccionado.
    carpeta = CARPETAS[tipo]
    capas = []
    errores_locales = []

    if not carpeta.exists() or not codigo or clave_codigo(codigo) == "SD":
        return capas, errores_locales

    for archivo in buscar_archivos(carpeta):
        try:
            nombre_base = archivo.relative_to(carpeta).with_suffix("").as_posix()
            nombre_comp = base_nombre_rio(nombre_base) if es_rio else nombre_base

            if archivo.suffix.lower() == ".gpkg":
                listado = pyogrio.list_layers(str(archivo))
                candidatas = []
                for fila in listado:
                    nombre_capa = fila[0]
                    tipo_geom = str(fila[1]).lower()
                    if nombre_capa is None or tipo_geom == "none":
                        continue
                    ref_capa = base_nombre_rio(str(nombre_capa)) if es_rio else str(nombre_capa)
                    if coincide_codigo(codigo, nombre_comp) or coincide_codigo(codigo, ref_capa):
                        candidatas.append(str(nombre_capa))
            else:
                candidatas = [None] if coincide_codigo(codigo, nombre_comp) else []

            for capa in candidatas:
                gdf = preparar_archivo(
                    str(archivo), capa, archivo.stat().st_mtime, tipo
                )
                if gdf is None:
                    continue
                nombre = nombre_base if capa is None else f"{nombre_base} - {capa}"
                capas.append((nombre, gdf))

        except Exception as exc:
            errores_locales.append(f"{archivo.name}: {exc}")

    return capas, errores_locales


def distancia_borde(geom, punto):

    try:
        return float(geom.boundary.distance(punto))
    except Exception:
        return float("inf")


def elegir_en_capa(gdf, punto):
    """Dentro de una capa, elige el polígono cuya salida está
    más cerca de la estación."""

    if len(gdf) == 1:
        idx = gdf.index[0]
        return int(idx), distancia_borde(gdf.geometry.loc[idx], punto)

    mejor = None
    mejor_d = float("inf")

    for idx in gdf.index:

        d = distancia_borde(gdf.geometry.loc[idx], punto)

        if d < mejor_d:
            mejor_d = d
            mejor = int(idx)

    return mejor, mejor_d


def buscar_cuenca_estacion(est, capas_subcuencas):
    """Devuelve ((nombre_capa, indice), metodo, dist_borde_grados)."""

    punto = Point(est["lon"], est["lat"])

    # ---- 1. Por código de estación (método exacto) ----
    coincidencias = [
        (nombre, gdf)
        for nombre, gdf in capas_subcuencas
        if coincide_codigo(est["codigo"], nombre)
    ]

    if coincidencias:

        mejor = None

        for nombre, gdf in coincidencias:

            idx, d = elegir_en_capa(gdf, punto)

            if mejor is None or d < mejor[2]:
                mejor = (nombre, idx, d)

        return (
            (mejor[0], mejor[1]),
            "Por código de estación",
            mejor[2],
        )

    # ---- 2. Estación en la salida (borde) de la cuenca ----
    mejor = None

    for nombre, gdf in capas_subcuencas:

        try:

            posiciones = gdf.sindex.query(
                punto.buffer(TOL_SALIDA)
            )

            for pos in posiciones:

                geom = gdf.geometry.iloc[pos]
                d = distancia_borde(geom, punto)

                if d <= TOL_SALIDA and (
                    mejor is None or d < mejor[2]
                ):
                    mejor = (nombre, int(gdf.index[pos]), d)

        except Exception:
            continue

    if mejor is not None:
        return (
            (mejor[0], mejor[1]),
            "Estación en la salida de la cuenca",
            mejor[2],
        )

    # ---- 3. Polígono más pequeño que contiene la estación ----
    candidatas = []

    for nombre, gdf in capas_subcuencas:

        try:

            mascara = gdf.geometry.covers(punto)

            for idx in gdf.index[mascara]:

                geom = gdf.geometry.loc[idx]

                candidatas.append(
                    (geom.area, nombre, int(idx), distancia_borde(geom, punto))
                )

        except Exception:
            continue

    if candidatas:

        candidatas.sort(key=lambda x: x[0])

        return (
            (candidatas[0][1], candidatas[0][2]),
            "Polígono más pequeño que contiene la estación",
            candidatas[0][3],
        )

    # ---- 4. Cuenca más cercana ----
    mejor = None

    for nombre, gdf in capas_subcuencas:

        try:

            distancias = gdf.geometry.distance(punto)

            idx = distancias.idxmin()
            d = float(distancias.loc[idx])

            if mejor is None or d < mejor[2]:
                mejor = (nombre, int(idx), d)

        except Exception:
            continue

    if mejor is not None and mejor[2] <= TOL_CERCANA:
        return (
            (mejor[0], mejor[1]),
            "Cuenca más cercana",
            mejor[2],
        )

    return None, "Sin cuenca asociada", None


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


# ============================================================
# 5b. RÍO QUE CORRESPONDE A LA CUENCA (carpeta rios_subcuencas)
# ============================================================

def base_nombre_rio(nombre_capa):
    """'ALT_001_RIO' -> 'ALT_001' (quita el sufijo _RIO / _RIOS)."""

    n = nombre_corto(nombre_capa)

    return re.sub(r"[\s_\-\.]*RIOS?$", "", n, flags=re.IGNORECASE)


def buscar_rio_de_cuenca(cuenca, est, capas_rios_sub):
    """Devuelve la lista de (nombre_capa, gdf) de la carpeta
    rios_subcuencas que corresponde a la cuenca (o a la estación)."""

    referencias = []

    if cuenca is not None:
        referencias.append(nombre_corto(cuenca[0]))

    referencias.append(est["codigo"])

    for ref in referencias:

        encontrados = [
            (nombre, gdf)
            for nombre, gdf in capas_rios_sub
            if coincide_codigo(ref, base_nombre_rio(nombre))
        ]

        if encontrados:
            return encontrados, ref

    return [], None


def rios_generales_recortados(poligono, capas_rios):
    """Respaldo: ríos de la carpeta 'rios' recortados a la cuenca."""

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

@st.cache_data(show_spinner=False, max_entries=1)
def mapa_estatico(clave, _paises, _capas_sub, _capas_rios):
    """Mapa general: límites nacionales, subcuencas y red hidrográfica."""
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.set_facecolor("#EAF2F8")

    # Subcuencas: bordes diferenciados y relleno transparente.
    for i, (_, gdf) in enumerate(_capas_sub):
        if gdf is None or gdf.empty:
            continue
        try:
            color = COLORES_CUENCAS[i % len(COLORES_CUENCAS)]
            gdf.plot(
                ax=ax, facecolor="none", edgecolor=color,
                linewidth=0.45, alpha=0.9
            )
        except Exception:
            continue

    # Red de ríos.
    for _, gdf in _capas_rios:
        if gdf is None or gdf.empty:
            continue
        try:
            gdf.plot(ax=ax, color="#168AAD", linewidth=0.35, alpha=0.85)
        except Exception:
            continue

    # Límites de países, cada uno con un color distinto.
    if _paises is not None and not _paises.empty:
        for _, fila in _paises.iterrows():
            try:
                color_pais = COLORES_PAIS.get(fila["pais"], "#333333")
                gpd.GeoSeries([fila.geometry], crs="EPSG:4326").plot(
                    ax=ax, facecolor="none", edgecolor=color_pais,
                    linewidth=1.8, zorder=5
                )
                punto = fila.geometry.representative_point()
                ax.annotate(
                    fila["pais"].upper(), (punto.x, punto.y),
                    ha="center", va="center", fontsize=10,
                    fontweight="bold", color=color_pais, zorder=6
                )
            except Exception:
                pass

        xmin, ymin, xmax, ymax = _paises.total_bounds
        mx = max((xmax - xmin) * 0.04, 0.35)
        my = max((ymax - ymin) * 0.04, 0.35)
        ax.set_xlim(xmin - mx, xmax + mx)
        ax.set_ylim(ymin - my, ymax + my)

    ax.set_aspect("equal")
    ax.grid(True, color="#B9C7D3", linewidth=0.3, linestyle="--", alpha=0.6)
    ax.tick_params(labelsize=7)
    ax.set_xlabel("Longitud", fontsize=8)
    ax.set_ylabel("Latitud", fontsize=8)
    ax.set_title(
        "Cuencas y red hidrográfica | Ecuador · Perú · Bolivia",
        fontsize=11, fontweight="bold"
    )

    leyenda = [
        Patch(facecolor="none", edgecolor=COLORES_PAIS["Ecuador"], linewidth=1.8, label="Límite Ecuador"),
        Patch(facecolor="none", edgecolor=COLORES_PAIS["Perú"], linewidth=1.8, label="Límite Perú"),
        Patch(facecolor="none", edgecolor=COLORES_PAIS["Bolivia"], linewidth=1.8, label="Límite Bolivia"),
        Line2D([0], [0], color="#168AAD", linewidth=1.2, label="Ríos"),
        Patch(facecolor="none", edgecolor="#7D3C98", linewidth=1.0, label="Límites de subcuencas"),
    ]
    ax.legend(handles=leyenda, loc="lower left", fontsize=7, framealpha=0.92)

    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


# ============================================================
# 7. ENCABEZADO Y PANEL LATERAL
# ============================================================

st.title(
    "Visor Hidrológico de Cuencas "
    "Andino-Amazónicas de Ecuador y Perú"
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

# ============================================================
# 8. CARGA INICIAL LIGERA
# ============================================================

with st.spinner("Cargando límites, subcuencas, ríos y estaciones..."):
    capas_sudamerica, e1 = cargar_carpeta("sudamerica")
    capas_subcuencas_mapa, e_sub_mapa = cargar_carpeta("subcuencas")
    capas_rios_mapa, e_rios_mapa = cargar_carpeta("rios")
    capas_puntos, e2 = cargar_carpeta("puntos")

errores = e1 + e_sub_mapa + e_rios_mapa + e2
clave_sud = firma(capas_sudamerica)
clave_pts = firma(capas_puntos)
clave_sub_mapa = firma(capas_subcuencas_mapa)
clave_rios_mapa = firma(capas_rios_mapa)

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

if not capas_rios_sub:
    st.warning(
        "No se encontraron archivos en la carpeta 'rios_subcuencas'. "
        "En el mapa de cuenca se usarán los ríos generales."
    )


# ============================================================
# 10. MAPA GENERAL (ESTÁTICO)
# ============================================================

with st.spinner("Generando mapa general..."):

    imagen = mapa_estatico(
        clave_sud + clave_sub_mapa + clave_rios_mapa,
        paises_gdf,
        capas_subcuencas_mapa,
        capas_rios_mapa,
    )

st.image(imagen, use_container_width=True)

# Liberar capas generales después de generar el mapa inicial.
del capas_subcuencas_mapa, capas_rios_mapa


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
# 12. MOSTRAR CUENCA, RÍO Y ESTACIÓN SELECCIONADOS
# ============================================================

if estacion_sel is not None:
    try:
        est = estaciones_por_clave[estacion_sel]

        with st.spinner(f"Cargando cuenca y río de {est['codigo']}..."):
            capas_subcuenca_sel, errores_sub = cargar_archivos_por_codigo(
                "subcuencas", est["codigo"], es_rio=False
            )
            capas_rio_sel, errores_rio = cargar_archivos_por_codigo(
                "rios_subcuencas", est["codigo"], es_rio=True
            )

        cuenca, _, _ = (
            buscar_cuenca_estacion(est, capas_subcuenca_sel)
            if capas_subcuenca_sel
            else (None, "Sin cuenca asociada", None)
        )
        poligono = obtener_poligono(cuenca, capas_subcuenca_sel)
        area_km2 = calcular_area_km2(poligono) if poligono is not None else None

        lista_rios = []
        for _, gdf_rio in capas_rio_sel:
            try:
                lista_rios.append(
                    gdf_rio[[gdf_rio.geometry.name]].to_json(drop_id=True)
                )
            except Exception:
                pass

        col_mapa, col_info = st.columns([3, 2])

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
                feature = {
                    "type": "Feature",
                    "geometry": poligono.__geo_interface__,
                    "properties": {},
                }
                folium.GeoJson(
                    feature,
                    name="Cuenca",
                    style_function=lambda f: {
                        "color": "#FFFFFF",
                        "weight": 3,
                        "opacity": 1,
                        "fillColor": COLOR_CUENCA_ACTIVA,
                        "fillOpacity": 0.35,
                    },
                    tooltip=(
                        f"Cuenca {nombre_corto(cuenca[0])}"
                        + (f" | Área: {area_km2:,.2f} km²" if area_km2 is not None else "")
                    ),
                ).add_to(mapa)

            grupo_rios = folium.FeatureGroup(name="Río", show=True)
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

            folium.CircleMarker(
                location=[est["lat"], est["lon"]],
                radius=7,
                color="#FFFFFF",
                weight=2,
                fill=True,
                fill_color=COLOR_ESTACION_ACTIVA,
                fill_opacity=1,
                tooltip=f"{est['codigo']} — {est['nombre']}",
            ).add_to(mapa)

            if poligono is not None:
                bx1, by1, bx2, by2 = poligono.bounds
                mapa.fit_bounds([[by1, bx1], [by2, bx2]], padding=(25, 25))

            Fullscreen(position="topleft").add_to(mapa)
            folium.LayerControl(collapsed=True).add_to(mapa)
            components.html(mapa.get_root().render(), height=620, scrolling=False)

        with col_info:
            st.markdown("#### Estación seleccionada")
            st.markdown(f"**País:** {est['pais']}")
            st.markdown(f"**Código:** {est['codigo']}")
            st.markdown(f"**Estación:** {est['nombre']}")

            if poligono is not None:
                st.markdown(f"**Cuenca:** {nombre_corto(cuenca[0])}")
                if area_km2 is not None:
                    st.metric("Área de la cuenca", f"{area_km2:,.2f} km²")
            else:
                st.warning(f"No se encontró la subcuenca de {est['codigo']}.")

            if capas_rio_sel:
                st.markdown(f"**Río:** {nombre_corto(capas_rio_sel[0][0])}")
            else:
                st.warning(f"No se encontró el río asociado a {est['codigo']}.")

    except Exception as exc:
        st.error("No se pudo cargar la cuenca seleccionada.")
        st.exception(exc)


# ============================================================
# 14. PIE DE PÁGINA
# ============================================================

st.caption("Visor Hidrológico BID | Ecuador · Perú · Bolivia")
