# -*- coding: utf-8 -*-
"""
DASHBOARD HIDROLÓGICO ANDINO-AMAZÓNICO
Ecuador - Perú - Bolivia

Estructura del repositorio GitHub (rama main):
bid/
├── app.py
├── requirements.txt
├── puntos/
│   ├── puntos_topologia.shp
│   ├── puntos_topologia.shx
│   ├── puntos_topologia.dbf
│   ├── puntos_topologia.prj
│   └── puntos_topologia.cpg
├── subcuencas/
│   ├── ALT_001.gpkg
│   ├── ALT_002.gpkg
│   └── ...
└── sudamerica/
    ├── sudamerica.shp
    ├── sudamerica.shx
    ├── sudamerica.dbf
    └── sudamerica.prj
"""

from pathlib import Path
import hashlib
import warnings

import streamlit as st
import geopandas as gpd
import fiona
import folium
from folium.plugins import Fullscreen, MousePosition, MiniMap
from streamlit_folium import st_folium

warnings.filterwarnings("ignore")

# ============================================================
# 1. CONFIGURACIÓN GENERAL
# ============================================================

ROOT = Path(__file__).resolve().parent
CARPETA_SUDAMERICA = ROOT / "sudamerica"
CARPETA_PUNTOS = ROOT / "puntos"
CARPETA_SUBCUENCAS = ROOT / "subcuencas"

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


st.set_page_config(
    page_title="Modelamiento Hidrológico Andino-Amazónico",
    page_icon="🌎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 2. FUNCIONES
# ============================================================

def color_por_nombre(nombre):
    """Color reproducible para cada archivo o capa."""
    valor = int(hashlib.md5(nombre.encode("utf-8")).hexdigest()[:8], 16)
    return PALETA[valor % len(PALETA)]


def buscar_archivos(carpeta, extensiones):
    """Busca archivos vectoriales dentro de una carpeta y subcarpetas."""
    if not carpeta.exists():
        return []

    encontrados = []
    for extension in extensiones:
        encontrados.extend(carpeta.rglob(f"*{extension}"))

    return sorted(set(encontrados), key=lambda x: x.name.lower())


@st.cache_data(show_spinner=False)
def leer_vector(ruta, fecha_modificacion):
    """
    Lee un SHP o GPKG.
    En GPKG lee todas las capas internas.
    """
    ruta = Path(ruta)
    capas = []

    if ruta.suffix.lower() == ".shp":
        try:
            gdf = gpd.read_file(ruta)
            capas.append((ruta.stem, gdf))
        except Exception as error:
            return [("ERROR", str(error))]

    elif ruta.suffix.lower() == ".gpkg":
        try:
            nombres_capas = fiona.listlayers(ruta)
            for nombre_capa in nombres_capas:
                try:
                    gdf = gpd.read_file(ruta, layer=nombre_capa)
                    capas.append((nombre_capa, gdf))
                except Exception as error:
                    capas.append((nombre_capa, str(error)))
        except Exception as error:
            return [("ERROR", str(error))]

    return capas


def preparar_geometria(gdf):
    """Valida geometría y transforma las coordenadas a WGS84."""
    if not isinstance(gdf, gpd.GeoDataFrame):
        return None, "El archivo no contiene una capa vectorial."

    if gdf.empty:
        return None, "La capa está vacía."

    if gdf.crs is None:
        return None, "No tiene sistema de coordenadas (CRS) definido."

    try:
        gdf = gdf[gdf.geometry.notna()].copy()
        gdf = gdf[~gdf.geometry.is_empty].copy()

        if gdf.empty:
            return None, "No contiene geometrías válidas."

        if gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        return gdf.reset_index(drop=True), None

    except Exception as error:
        return None, str(error)


def campos_atributos(gdf, limite=5):
    """Selecciona campos para mostrar en la información emergente."""
    campos = []

    for campo in gdf.columns:
        if campo == gdf.geometry.name:
            continue

        if gdf[campo].notna().any():
            campos.append(campo)

        if len(campos) >= limite:
            break

    return campos


def agregar_capa_poligono(mapa, gdf, nombre, color):
    """Dibuja cuencas y subcuencas con colores independientes."""
    campos = campos_atributos(gdf)

    tooltip = None
    popup = None

    if campos:
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

    folium.GeoJson(
        data=gdf.to_json(),
        name=nombre,
        style_function=lambda feature: {
            "fillColor": color,
            "color": color,
            "weight": 1.4,
            "fillOpacity": 0.30,
            "opacity": 0.95,
        },
        highlight_function=lambda feature: {
            "color": "#ffffff",
            "weight": 3,
            "fillOpacity": 0.55,
        },
        tooltip=tooltip,
        popup=popup,
        show=True,
    ).add_to(mapa)


def agregar_capa_puntos(mapa, gdf, nombre, color):
    """Dibuja las estaciones como marcadores circulares."""
    campos = campos_atributos(gdf)

    tooltip = None
    popup = None

    if campos:
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

    folium.GeoJson(
        data=gdf.to_json(),
        name=nombre,
        marker=folium.CircleMarker(
            radius=5,
            color="#ffffff",
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=1,
        ),
        tooltip=tooltip,
        popup=popup,
        show=True,
    ).add_to(mapa)


def calcular_extension(lista_gdf):
    """Calcula la extensión conjunta de todas las capas."""
    if not lista_gdf:
        return [-4.0, -75.0], None

    limites = [gdf.total_bounds for gdf in lista_gdf]

    xmin = min(b[0] for b in limites)
    ymin = min(b[1] for b in limites)
    xmax = max(b[2] for b in limites)
    ymax = max(b[3] for b in limites)

    centro = [(ymin + ymax) / 2, (xmin + xmax) / 2]
    bounds = [[ymin, xmin], [ymax, xmax]]

    return centro, bounds


# ============================================================
# 3. ENCABEZADO
# ============================================================

st.markdown(
    f"""
    <div style="
        background: linear-gradient(115deg, #082f49, #075985, #0f766e);
        padding: 27px 30px;
        border-radius: 13px;
        color: white;
        margin-bottom: 20px;">
        <div style="font-size:12px;letter-spacing:2px;opacity:0.85;">
            PLATAFORMA DE MODELAMIENTO HIDROLÓGICO
        </div>
        <h1 style="color:white;font-size:29px;margin:10px 0;">
            {TITULO}
        </h1>
        <div style="font-size:14px;opacity:0.9;">
            Ecuador · Perú · Bolivia | Visor geoespacial de cuencas y estaciones
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# 4. IDENTIFICAR ARCHIVOS DEL REPOSITORIO
# ============================================================

# Puntos: tu repositorio tiene puntos_topologia.shp
archivos_puntos = buscar_archivos(CARPETA_PUNTOS, [".shp", ".gpkg"])

# Sudamérica: busca sudamerica.shp y también admite GPKG
archivos_sudamerica = buscar_archivos(
    CARPETA_SUDAMERICA, [".shp", ".gpkg"]
)

# Subcuencas: admite todos los GPKG y SHP de la carpeta
archivos_subcuencas = buscar_archivos(
    CARPETA_SUBCUENCAS, [".gpkg", ".shp"]
)

# ============================================================
# 5. PANEL LATERAL
# ============================================================

st.sidebar.title("🗺️ Panel de capas")
st.sidebar.caption("Control de visualización del mapa")

ver_sudamerica = st.sidebar.checkbox(
    "Límites de Sudamérica", value=True
)
ver_puntos = st.sidebar.checkbox(
    "Estaciones hidrológicas", value=True
)
ver_subcuencas = st.sidebar.checkbox(
    "Cuencas y subcuencas", value=True
)
ver_google = st.sidebar.checkbox(
    "Google Satélite", value=True
)

st.sidebar.divider()
st.sidebar.markdown("**Archivos detectados**")
st.sidebar.write(f"Sudamérica: {len(archivos_sudamerica)}")
st.sidebar.write(f"Archivos de puntos: {len(archivos_puntos)}")
st.sidebar.write(f"Archivos de subcuencas: {len(archivos_subcuencas)}")

if st.sidebar.button("🔄 Actualizar capas", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

# ============================================================
# 6. CARGAR INFORMACIÓN GEOGRÁFICA
# ============================================================

capas_sudamerica = []
capas_puntos = []
capas_subcuencas = []
errores = []

with st.spinner("Leyendo archivos geográficos del repositorio..."):

    # -------------------------------
    # Sudamérica
    # -------------------------------
    for archivo in archivos_sudamerica:
        for nombre_capa, resultado in leer_vector(
            str(archivo), archivo.stat().st_mtime
        ):
            if isinstance(resultado, str):
                errores.append(f"{archivo.name}: {resultado}")
                continue

            gdf, error = preparar_geometria(resultado)

            if error:
                errores.append(f"{archivo.name}: {error}")
                continue

            capas_sudamerica.append(
                (f"Sudamérica - {nombre_capa}", gdf)
            )

    # -------------------------------
    # Estaciones
    # -------------------------------
    for archivo in archivos_puntos:
        for nombre_capa, resultado in leer_vector(
            str(archivo), archivo.stat().st_mtime
        ):
            if isinstance(resultado, str):
                errores.append(f"{archivo.name}: {resultado}")
                continue

            gdf, error = preparar_geometria(resultado)

            if error:
                errores.append(f"{archivo.name}: {error}")
                continue

            capas_puntos.append(
                (f"{archivo.stem} - {nombre_capa}", gdf)
            )

    # -------------------------------
    # Cuencas y subcuencas
    # -------------------------------
    for archivo in archivos_subcuencas:
        for nombre_capa, resultado in leer_vector(
            str(archivo), archivo.stat().st_mtime
        ):
            if isinstance(resultado, str):
                errores.append(
                    f"{archivo.name} / {nombre_capa}: {resultado}"
                )
                continue

            gdf, error = preparar_geometria(resultado)

            if error:
                errores.append(
                    f"{archivo.name} / {nombre_capa}: {error}"
                )
                continue

            capas_subcuencas.append(
                (f"{archivo.stem} - {nombre_capa}", gdf)
            )

# ============================================================
# 7. INDICADORES
# ============================================================

total_puntos = sum(len(gdf) for _, gdf in capas_puntos)
total_elementos = sum(len(gdf) for _, gdf in capas_subcuencas)

m1, m2, m3, m4 = st.columns(4)

m1.metric("Capas de Sudamérica", len(capas_sudamerica))
m2.metric("Estaciones", f"{total_puntos:,}")
m3.metric("Archivos hidrográficos", len(archivos_subcuencas))
m4.metric("Elementos hidrográficos", f"{total_elementos:,}")

# ============================================================
# 8. CONSTRUIR MAPA
# ============================================================

st.subheader("Visor geoespacial de las cuencas")

todas_las_capas = []

for _, gdf in capas_sudamerica:
    todas_las_capas.append(gdf)

for _, gdf in capas_puntos:
    todas_las_capas.append(gdf)

for _, gdf in capas_subcuencas:
    todas_las_capas.append(gdf)

centro, bounds = calcular_extension(todas_las_capas)

mapa = folium.Map(
    location=centro,
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True,
)

# Fondo satelital
if ver_google:
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google Satellite",
        name="Google Satélite",
        overlay=False,
        control=True,
        show=True,
        max_zoom=20,
    ).add_to(mapa)

# Fondo alternativo
folium.TileLayer(
    "OpenStreetMap",
    name="Mapa de calles",
    overlay=False,
    control=True,
    show=not ver_google,
).add_to(mapa)

# -------------------------------
# Dibujar Sudamérica
# -------------------------------
if ver_sudamerica:
    for nombre, gdf in capas_sudamerica:
        agregar_capa_poligono(
            mapa, gdf, nombre, "#263746"
        )

# -------------------------------
# Dibujar subcuencas
# Cada archivo recibe su propio color
# -------------------------------
if ver_subcuencas:
    for nombre, gdf in capas_subcuencas:
        agregar_capa_poligono(
            mapa, gdf, nombre, color_por_nombre(nombre)
        )

# -------------------------------
# Dibujar puntos
# -------------------------------
if ver_puntos:
    for nombre, gdf in capas_puntos:
        agregar_capa_puntos(
            mapa, gdf, nombre, "#ff2020"
        )

Fullscreen(position="topleft").add_to(mapa)

MousePosition(
    position="bottomright",
    separator=" | ",
    prefix="Coordenadas",
    num_digits=5,
).add_to(mapa)

MiniMap(
    toggle_display=True,
    minimized=True,
).add_to(mapa)

folium.LayerControl(
    collapsed=False,
    position="topright",
).add_to(mapa)

if bounds:
    mapa.fit_bounds(bounds, padding=(20, 20))

st_folium(
    mapa,
    use_container_width=True,
    height=700,
    returned_objects=[],
    key="mapa_hidrologico_andino_amazonico",
)

# ============================================================
# 9. LEYENDA
# ============================================================

st.subheader("Leyenda de capas")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Límites geográficos**")
    st.markdown(
        '<span style="display:inline-block;width:14px;height:14px;'
        'background:#263746;margin-right:8px;"></span>Sudamérica',
        unsafe_allow_html=True,
    )

    st.markdown("**Estaciones hidrológicas**")
    st.markdown(
        '<span style="display:inline-block;width:12px;height:12px;'
        'border-radius:50%;background:#ff2020;margin-right:8px;"></span>'
        'Puntos de estaciones',
        unsafe_allow_html=True,
    )

with col2:
    st.markdown("**Cuencas y subcuencas**")

    if capas_subcuencas:
        for nombre, _ in capas_subcuencas:
            color = color_por_nombre(nombre)
            st.markdown(
                f'<span style="display:inline-block;width:14px;height:14px;'
                f'background:{color};margin-right:8px;"></span>{nombre}',
                unsafe_allow_html=True,
            )
    else:
        st.info("No se encontraron archivos válidos en subcuencas.")

# ============================================================
# 10. ESTADO DE LOS ARCHIVOS
# ============================================================

with st.expander("Estado de lectura de archivos"):
    st.write(f"Capas de Sudamérica cargadas: {len(capas_sudamerica)}")
    st.write(f"Capas de puntos cargadas: {len(capas_puntos)}")
    st.write(f"Capas de subcuencas cargadas: {len(capas_subcuencas)}")

    if errores:
        st.warning(f"Se encontraron {len(errores)} observaciones.")
        for error in errores:
            st.write(f"- {error}")
    else:
        st.success("Los archivos detectados se leyeron correctamente.")

# ============================================================
# 11. PIE DE PÁGINA
# ============================================================

st.markdown(
    """
    <hr>
    <div style="text-align:center;color:#64748b;font-size:12px;padding:8px;">
        Modelamiento Hidrológico de las Cuencas Andino-Amazónicas
        <br>
        Ecuador · Perú · Bolivia
    </div>
    """,
    unsafe_allow_html=True,
)
