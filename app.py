# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

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

HEADERS = [
    "date", "barrio", "factor_riesgo", "delitos_relacionados",
    "ligado_estructura", "nombre_estructura", "observaciones",
    "lat", "lng", "maps_link"
]

# ========= GSPREAD HELPERS =========
@st.cache_resource(show_spinner=False)
def _open_worksheet():
    """Abre (o crea) la hoja 'Respuestas' con encabezados."""
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
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(HEADERS)
    return ws

def append_row(data: dict):
    ws = _open_worksheet()
    # Fórmula HYPERLINK que se evalúa en Sheets
    maps_formula = f'=HYPERLINK("https://www.google.com/maps?q={data["lat"]},{data["lng"]}","Ver en Maps")'
    ws.append_row([
        data["date"], data["barrio"], data["factor_riesgo"],
        data["delitos_relacionados"], data["ligado_estructura"],
        data["nombre_estructura"], data["observaciones"],
        data["lat"], data["lng"], maps_formula
    ], value_input_option="USER_ENTERED")

@st.cache_data(ttl=30, show_spinner=False)
def read_all_rows() -> pd.DataFrame:
    ws = _open_worksheet()
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

# ========= UI =========
st.title("📍 Microdespliegue Pavas – Encuestas georreferenciadas")

tabs = st.tabs(["📝 Formulario", "🗺️ Mapa & Datos"])

# ======= TAB 1: FORM =======
with tabs[0]:
    left, right = st.columns([0.55, 0.45], gap="large")

    with left:
        st.subheader("Selecciona un punto en el mapa")
        st.caption("Usa el ícono 🎯 (Localizar) para centrar el mapa en tu ubicación y luego haz un clic para registrar el punto.")

        # Centro por defecto (Pavas)
        default_center = [9.948, -84.144]

        # Si ya hay punto elegido, centra allí
        center = default_center
        if st.session_state.get("clicked"):
            center = [st.session_state["clicked"]["lat"], st.session_state["clicked"]["lng"]]

        # Mapa con control de geolocalización del navegador
        m = folium.Map(location=center, zoom_start=13, control_scale=True)
        LocateControl(auto_start=False, flyTo=True, keepCurrentZoomLevel=False).add_to(m)

        clicked_state = st.session_state.get("clicked", None)
        if clicked_state:
            folium.Marker(
                location=[clicked_state["lat"], clicked_state["lng"]],
                tooltip="Ubicación seleccionada"
            ).add_to(m)

        map_ret = st_folium(m, height=520, use_container_width=True)

        # Captura de click en el mapa
        if map_ret and map_ret.get("last_clicked"):
            st.session_state["clicked"] = {
                "lat": round(map_ret["last_clicked"]["lat"], 6),
                "lng": round(map_ret["last_clicked"]["lng"], 6),
            }

        cols_coords = st.columns(3)
        lat_val = st.session_state.get("clicked", {}).get("lat")
        lng_val = st.session_state.get("clicked", {}).get("lng")
        cols_coords[0].metric("Latitud", lat_val if lat_val is not None else "—")
        cols_coords[1].metric("Longitud", lng_val if lng_val is not None else "—")
        if cols_coords[2].button("Limpiar selección"):
            st.session_state["clicked"] = None
            st.rerun()

    with right:
        st.subheader("Formulario de encuesta")
        with st.form("form_encuesta", clear_on_submit=True):
            barrio = st.text_input("Barrio *")
            factor = st.text_area("Factor de riesgo *", height=70,
                                  placeholder="Ej.: consumo de drogas, portación de armas, ventas ilícitas, etc.")
            delitos = st.text_area("Delitos relacionados al factor *", height=70,
                                   placeholder="Ej.: venta de droga, robos, hurtos, sicariato…")

            ligado = st.radio("Ligado a estructura criminal *", ["No", "Sí"], index=0, horizontal=True)
            nombre_estructura = st.text_input("Nombre de la estructura ligada (si aplica)")

            observ = st.text_area("Observaciones", height=90)

            submitted = st.form_submit_button("Guardar en Google Sheets")

        if submitted:
            # Validaciones mínimas
            errors = []
            if not barrio.strip():
                errors.append("Indica el **Barrio**.")
            if not factor.strip():
                errors.append("Indica el **factor de riesgo**.")
            if not delitos.strip():
                errors.append("Indica los **delitos relacionados**.")
            if lat_val is None or lng_val is None:
                errors.append("Selecciona un **punto en el mapa** (lat/lng).")

            if errors:
                st.error("• " + "\n• ".join(errors))
            else:
                payload = {
                    # Fecha sin hora
                    "date": datetime.now(TZ).strftime("%d-%m-%Y"),
                    "barrio": barrio.strip(),
                    "factor_riesgo": factor.strip(),
                    "delitos_relacionados": delitos.strip(),
                    "ligado_estructura": ligado,  # "Sí" o "No"
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
        # Mapa con todas las encuestas
        m2 = folium.Map(location=[9.948, -84.144], zoom_start=13, control_scale=True)
        LocateControl(auto_start=False).add_to(m2)
        cluster = MarkerCluster().add_to(m2)
        for _, r in df.iterrows():
            lat, lng = r.get("lat"), r.get("lng")
            if lat and lng:
                popup = folium.Popup(
                    html=(
                        f"<b>Barrio:</b> {r.get('barrio','')}<br>"
                        f"<b>Factor:</b> {r.get('factor_riesgo','')}<br>"
                        f"<b>Delitos:</b> {r.get('delitos_relacionados','')}<br>"
                        f"<b>Estructura:</b> {r.get('ligado_estructura','')} "
                        f"{r.get('nombre_estructura','')}<br>"
                        f"<b>Obs:</b> {r.get('observaciones','')}<br>"
                        f"<b>Fecha:</b> {r.get('date','')}"
                    ),
                    max_width=350,
                )
                folium.Marker(location=[float(lat), float(lng)], popup=popup).add_to(cluster)
        st_folium(m2, height=520, use_container_width=True)

        st.markdown("#### Tabla de respuestas")
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "⬇️ Descargar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="encuestas_pavas.csv",
            mime="text/csv",
        )










