# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import random

import gspread
from google.oauth2.service_account import Credentials

import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, LocateControl

st.set_page_config(page_title="Microdespliegue Pavas – Encuestas", layout="wide")

# ========= CONFIG =========
SHEET_ID = "1VfejN3kOziB7jhwG4P3Q8Q9B_s0uJatg1kzwELMO0fU"
WORKSHEET_NAME = "Respuestas"   # se crea si no existe
TZ = ZoneInfo("America/Costa_Rica")

# --- Catálogo de factores (orden fijo) ---
FACTORES = [
    "Calles sin iluminación adecuada por la noche.",
    "Calles con poca visibilidad por vegetación, muros o abandono.",
    "Zonas con lotes baldíos o propiedades abandonadas.",
    "Presencia de personas desconocidas merodeando sin razón aparente.",
    "Personas consumiendo drogas o alcohol en la vía pública.",
    "Presencia constante de motocicletas sin placas o “sospechosas”.",
    "Ausencia de presencia policial visible o cercana.",
    "Accesos rápidos de escape desde la zona (calles, ríos, callejones).",
    "Espacios públicos deteriorados (parques, aceras, etc.).",
    "Ruido excesivo o escándalos a cualquier hora del día.",
    "Falta de cámaras de seguridad en la zona.",
    "Estacionamientos inseguros o sin control.",
    "Grafitis o pintas intimidantes (no artísticas).",
    "Ventas informales o con presencia agresiva.",
    "Frecuente presencia de menores de edad sin supervisión en la zona.",
    "Ingreso fácil a zonas no vigiladas (playas, callejones, senderos).",
    "Altos niveles de basura o suciedad en la zona.",
    "Zonas donde se han dado riñas o enfrentamientos recientemente.",
    "Personas en situación de calle vulnerables o con conductas agresivas.",
    "Negocios abandonados o cerrados de forma permanente.",
    "Vehículos sospechosos parqueados por tiempo prolongado.",
    "Otro: especificar.",
]

# --- Colores por factor (22 colores) ---
FACTOR_COLORS = {
    FACTORES[0]:  "#e41a1c",  FACTORES[1]:  "#377eb8",  FACTORES[2]:  "#4daf4a",
    FACTORES[3]:  "#984ea3",  FACTORES[4]:  "#ff7f00",  FACTORES[5]:  "#ffff33",
    FACTORES[6]:  "#a65628",  FACTORES[7]:  "#f781bf",  FACTORES[8]:  "#999999",
    FACTORES[9]:  "#1b9e77",  FACTORES[10]: "#d95f02",  FACTORES[11]: "#7570b3",
    FACTORES[12]: "#e7298a",  FACTORES[13]: "#66a61e",  FACTORES[14]: "#e6ab02",
    FACTORES[15]: "#a6761d",  FACTORES[16]: "#1f78b4",  FACTORES[17]: "#b2df8a",
    FACTORES[18]: "#fb9a99",  FACTORES[19]: "#cab2d6",  FACTORES[20]: "#fdbf6f",
    FACTORES[21]: "#b15928",
}

HEADERS = [
    "date", "barrio", "factores", "delitos_relacionados",
    "ligado_estructura", "nombre_estructura", "observaciones",
    "lat", "lng", "maps_link"
]

# ========= GSPREAD HELPERS =========
@st.cache_resource(show_spinner=False)
def _open_worksheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=scopes
    )
    client = gspread.authorize(credentials)
    sh = client.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=20)
        ws.append_row(HEADERS)
    if not ws.row_values(1):
        ws.append_row(HEADERS)
    return ws

def append_row(data: dict):
    ws = _open_worksheet()
    maps_formula = f'=HYPERLINK("https://www.google.com/maps?q={data["lat"]},{data["lng"]}","Ver en Maps")'
    ws.append_row([
        data["date"], data["barrio"], data["factores"],
        data["delitos_relacionados"], data["ligado_estructura"],
        data["nombre_estructura"], data["observaciones"],
        data["lat"], data["lng"], maps_formula
    ], value_input_option="USER_ENTERED")

@st.cache_data(ttl=30, show_spinner=False)
def read_all_rows() -> pd.DataFrame:
    ws = _open_worksheet()
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

# ========= UTILS =========
def _jitter(idx: int, base: float = 0.00008) -> float:
    random.seed(idx)
    return (random.random() - 0.5) * base

def _legend_html() -> str:
    items = "".join(
        f'<div style="display:flex;align-items:center;margin-bottom:4px">'
        f'<span style="width:12px;height:12px;background:{FACTOR_COLORS[f]};display:inline-block;margin-right:8px;border:1px solid #333;"></span>'
        f'<span style="font-size:12px">{f}</span></div>'
        for f in FACTORES
    )
    return (
        '<div style="position: fixed; bottom: 20px; right: 20px; z-index:9999; '
        'background: rgba(255,255,255,0.95); padding:10px; border:1px solid #999; '
        'border-radius:6px; max-height:300px; overflow:auto; width:320px">'
        '<b>Leyenda – Factores</b><hr style="margin:6px 0;">'
        f'{items}</div>'
    )

# ========= UI =========
st.title("📍 Microdespliegue Pavas – Encuestas georreferenciadas")

tabs = st.tabs(["📝 Formulario", "🗺️ Mapa & Datos"])

# ======= TAB 1: FORM =======
with tabs[0]:
    left, right = st.columns([0.55, 0.45], gap="large")

    with left:
        st.subheader("Selecciona un punto en el mapa")
        st.caption("Usa el ícono 🎯 (Localizar) para centrar el mapa y luego haz un clic para registrar el punto.")

        default_center = [9.948, -84.144]
        clicked = st.session_state.get("clicked") or {}
        center = [clicked.get("lat", default_center[0]), clicked.get("lng", default_center[1])]

        m = folium.Map(location=center, zoom_start=13, control_scale=True)
        LocateControl(auto_start=False, flyTo=True).add_to(m)

        if clicked.get("lat") is not None and clicked.get("lng") is not None:
            folium.CircleMarker(
                location=[clicked["lat"], clicked["lng"]],
                radius=8, color="#000", weight=1, fill=True, fill_color="#2dd4bf", fill_opacity=0.9,
                tooltip="Ubicación seleccionada"
            ).add_to(m)

        map_ret = st_folium(m, height=520, use_container_width=True)

        if map_ret and map_ret.get("last_clicked"):
            st.session_state["clicked"] = {
                "lat": round(map_ret["last_clicked"]["lat"], 6),
                "lng": round(map_ret["last_clicked"]["lng"], 6),
            }
            clicked = st.session_state["clicked"]

        cols_coords = st.columns(3)
        lat_val = clicked.get("lat")
        lng_val = clicked.get("lng")
        cols_coords[0].metric("Latitud", lat_val if lat_val is not None else "—")
        cols_coords[1].metric("Longitud", lng_val if lng_val is not None else "—")
        if cols_coords[2].button("Limpiar selección"):
            st.session_state.pop("clicked", None)
            st.rerun()

    with right:
        st.subheader("Formulario de encuesta")

        with st.form("form_encuesta", clear_on_submit=True):
            barrio = st.text_input("Barrio *")

            # 🔹 AHORA: selección múltiple de factores (del catálogo)
            factores_sel = st.multiselect(
                "Factor(es) de riesgo *",
                options=FACTORES,
                placeholder="Selecciona uno o varios factores",
            )

            delitos = st.text_area("Delitos relacionados al/los factor(es) *", height=70,
                                   placeholder="Ej.: venta de droga, robos, hurtos, sicariato…")

            ligado = st.radio("Ligado a estructura criminal *", ["No", "Sí"], index=0, horizontal=True)
            nombre_estructura = st.text_input("Nombre de la estructura ligada (si aplica)")
            observ = st.text_area("Observaciones", height=90)

            submitted = st.form_submit_button("Guardar en Google Sheets")

        if submitted:
            errors = []
            if not barrio.strip():
                errors.append("Indica el **Barrio**.")
            if not factores_sel:
                errors.append("Selecciona al menos **un factor de riesgo**.")
            if not delitos.strip():
                errors.append("Indica los **delitos relacionados**.")
            if lat_val is None or lng_val is None:
                errors.append("Selecciona un **punto en el mapa** (lat/lng).")

            if errors:
                st.error("• " + "\n• ".join(errors))
            else:
                payload = {
                    "date": datetime.now(TZ).strftime("%d-%m-%Y"),
                    "barrio": barrio.strip(),
                    # Guardamos como CSV legible
                    "factores": ", ".join(factores_sel),
                    "delitos_relacionados": delitos.strip(),
                    "ligado_estructura": ligado,
                    "nombre_estructura": nombre_estructura.strip(),
                    "observaciones": observ.strip(),
                    "lat": lat_val,
                    "lng": lng_val,
                }
                try:
                    append_row(payload)
                    st.success("✅ Respuesta guardada correctamente en Google Sheets.")
                except Exception as e:
                    st.error(f"❌ No se pudo guardar en Google Sheets.\n\n{e}")

# ======= TAB 2: MAPA & DATOS =======
with tabs[1]:
    st.subheader("Visualización de encuestas")

    df = read_all_rows()
    if df.empty:
        st.info("Aún no hay registros.")
    else:
        # =======================
        # Filtros por Factor/es
        # =======================
        st.markdown("**Filtro por factor de riesgo:**")
        factores_unicos = []
        for v in df["factores"].dropna().tolist():
            for f in [x.strip() for x in str(v).split(",") if x.strip()]:
                if f not in factores_unicos:
                    factores_unicos.append(f)
        # Aseguramos orden según catálogo original
        factores_unicos = [f for f in FACTORES if f in factores_unicos]

        filtros = st.multiselect(
            "Mostrar únicamente registros que contengan cualquiera de estos factores",
            options=factores_unicos,
            default=[],
            placeholder="(Sin filtro = muestra todos)"
        )

        # =======================
        # Mapa
        # =======================
        m2 = folium.Map(location=[9.948, -84.144], zoom_start=13, control_scale=True)
        LocateControl(auto_start=False).add_to(m2)
        cluster = MarkerCluster().add_to(m2)

        # Leyenda
        legend = _legend_html()
        folium.map.LayerControl().add_to(m2)
        m2.get_root().html.add_child(folium.Element(legend))

        # Renderizado con color por factor.
        # Si un registro tiene varios factores y el filtro incluye varios, se dibuja una marca por factor (con jitter leve).
        idx_global = 0
        for _, r in df.iterrows():
            lat, lng = r.get("lat"), r.get("lng")
            if not (lat and lng):
                continue

            factores_row = [x.strip() for x in str(r.get("factores", "")).split(",") if x.strip()]
            # Si hay filtros, requerimos intersección
            if filtros:
                factores_mostrar = [f for f in factores_row if f in filtros]
                if not factores_mostrar:
                    continue
            else:
                factores_mostrar = factores_row if factores_row else ["(Sin factor)"]

            # Dibujar 1 marca por factor a mostrar
            for i, f in enumerate(factores_mostrar):
                color = FACTOR_COLORS.get(f, "#555555")
                # Jitter para que no queden exactamente sobre el mismo punto
                jlat = float(lat) + _jitter(idx_global + i)
                jlng = float(lng) + _jitter(idx_global + i + 101)
                popup = folium.Popup(
                    html=(
                        f"<b>Fecha:</b> {r.get('date','')}<br>"
                        f"<b>Barrio:</b> {r.get('barrio','')}<br>"
                        f"<b>Factor:</b> {f}<br>"
                        f"<b>Delitos:</b> {r.get('delitos_relacionados','')}<br>"
                        f"<b>Estructura:</b> {r.get('ligado_estructura','')} "
                        f"{r.get('nombre_estructura','')}<br>"
                        f"<b>Obs:</b> {r.get('observaciones','')}"
                    ),
                    max_width=350,
                )
                folium.CircleMarker(
                    location=[jlat, jlng],
                    radius=8, color="#000", weight=1, fill=True,
                    fill_color=color, fill_opacity=0.95, popup=popup
                ).add_to(cluster)
            idx_global += 1

        st_folium(m2, height=540, use_container_width=True)

        # =======================
        # Tabla + descarga
        # =======================
        st.markdown("#### Tabla de respuestas")
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "⬇️ Descargar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="encuestas_pavas.csv",
            mime="text/csv",
        )





