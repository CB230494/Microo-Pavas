# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import random, re

import gspread
from google.oauth2.service_account import Credentials

import folium
from streamlit_folium import st_folium
from folium.plugins import MarkerCluster, LocateControl

st.set_page_config(page_title="Microdespliegue Pavas – Encuestas", layout="wide")

# ========= CONFIG =========
SHEET_ID = "1VfejN3kOziB7jhwG4P3Q8Q9B_s0uJatg1kzwELMO0fU"
WORKSHEET_NAME = "Respuestas"
TZ = ZoneInfo("America/Costa_Rica")

# --- Factores y colores (orden fijo) ---
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
FACTOR_COLORS = {
    FACTORES[0]:"#e41a1c", FACTORES[1]:"#377eb8", FACTORES[2]:"#4daf4a",
    FACTORES[3]:"#984ea3", FACTORES[4]:"#ff7f00", FACTORES[5]:"#ffff33",
    FACTORES[6]:"#a65628", FACTORES[7]:"#f781bf", FACTORES[8]:"#999999",
    FACTORES[9]:"#1b9e77", FACTORES[10]:"#d95f02", FACTORES[11]:"#7570b3",
    FACTORES[12]:"#e7298a", FACTORES[13]:"#66a61e", FACTORES[14]:"#e6ab02",
    FACTORES[15]:"#a6761d", FACTORES[16]:"#1f78b4", FACTORES[17]:"#b2df8a",
    FACTORES[18]:"#fb9a99", FACTORES[19]:"#cab2d6", FACTORES[20]:"#fdbf6f",
    FACTORES[21]:"#b15928",
}

# Cabecera recomendada (sin lat/lng)
NEW_HEADERS = [
    "date","barrio","factores","delitos_relacionados",
    "ligado_estructura","nombre_estructura","observaciones",
    "maps_link"
]

# ========= GSPREAD =========
@st.cache_resource(show_spinner=False)
def _ws():
    scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    client = gspread.authorize(creds)
    try:
        ws = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = client.open_by_key(SHEET_ID).add_worksheet(WORKSHEET_NAME, rows=1000, cols=20)
        ws.append_row(NEW_HEADERS)
    if not ws.row_values(1):
        ws.append_row(NEW_HEADERS)
    _ensure_schema(ws)
    return ws

def _headers(ws): return [h.strip() for h in ws.row_values(1)]

def _hex_to_rgb01(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2],16)/255.0, "green": int(h[2:4],16)/255.0, "blue": int(h[4:6],16)/255.0}

def _ensure_schema(ws):
    headers = _headers(ws)
    # quitar lat/lng si existieran
    for name in ["lat","lng"]:
        if name in headers:
            ws.delete_columns(headers.index(name)+1)
            headers = _headers(ws)
    # asegurar maps_link
    if "maps_link" not in headers:
        ws.update_cell(1, len(headers)+1, "maps_link")

def append_row(data: dict):
    """
    Guarda fila siguiendo el orden actual de la hoja.
    - maps_link como URL (no fórmula), para leer lat/lng después.
    - Colorea la celda del factor.
    - Retro-compat con 'timestamp' y 'factor_riesgo' si existieran.
    """
    ws = _ws()
    headers = _headers(ws)
    maps_url = f'https://www.google.com/maps?q={data["lat"]},{data["lng"]}'

    values = {
        "date": data.get("date",""),
        "barrio": data.get("barrio",""),
        "factores": data.get("factores",""),
        "delitos_relacionados": data.get("delitos_relacionados",""),
        "ligado_estructura": data.get("ligado_estructura",""),
        "nombre_estructura": data.get("nombre_estructura",""),
        "observaciones": data.get("observaciones",""),
        "maps_link": maps_url,
        # compat viejo:
        "timestamp": data.get("date",""),
        "factor_riesgo": data.get("factores",""),
    }

    ws.append_row([values.get(c,"") for c in headers], value_input_option="USER_ENTERED")
    last_row = len(ws.get_all_values())

    # Pintar celda del factor
    col = None
    if "factores" in headers: col = headers.index("factores")+1
    elif "factor_riesgo" in headers: col = headers.index("factor_riesgo")+1
    if col:
        color = FACTOR_COLORS.get(data.get("factores",""), "#ffffff")
        ws.format(gspread.utils.rowcol_to_a1(last_row, col), {"backgroundColor": _hex_to_rgb01(color)})

@st.cache_data(ttl=30, show_spinner=False)
def read_df() -> pd.DataFrame:
    """
    Devuelve DF normalizado. Reconstruye lat/lng desde maps_link:
    - Si es URL directa: la parsea.
    - Si es texto 'Ver en Maps': lee la fórmula HYPERLINK y extrae la URL.
    """
    ws = _ws()
    records = ws.get_all_records()
    df_raw = pd.DataFrame(records)

    # leer fórmulas para casos 'Ver en Maps'
    all_formulas = ws.get_all_values(value_render_option="FORMULA")
    headers = all_formulas[0] if all_formulas else []
    maps_col_idx = headers.index("maps_link") if "maps_link" in headers else None
    maps_formulas = []
    if maps_col_idx is not None:
        for row in all_formulas[1:]:
            maps_formulas.append(row[maps_col_idx] if maps_col_idx < len(row) else "")

    df = pd.DataFrame()
    # columnas bases
    if "date" in df_raw.columns: df["date"] = df_raw["date"]
    elif "timestamp" in df_raw.columns: df["date"] = df_raw["timestamp"]
    else: df["date"] = ""
    df["barrio"] = df_raw["barrio"] if "barrio" in df_raw.columns else ""
    if "factores" in df_raw.columns: df["factores"] = df_raw["factores"]
    elif "factor_riesgo" in df_raw.columns: df["factores"] = df_raw["factor_riesgo"]
    else: df["factores"] = ""
    for c in ["delitos_relacionados","ligado_estructura","nombre_estructura","observaciones"]:
        df[c] = df_raw[c] if c in df_raw.columns else ""
    df["maps_link"] = df_raw["maps_link"] if "maps_link" in df_raw.columns else ""

    # Extraer lat/lng
    lats, lngs = [], []
    url_pat = re.compile(r"https?://.*maps\?q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
    hyp_pat = re.compile(r'HYPERLINK\("https?://.*maps\?q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)"')
    for i, link in enumerate(df["maps_link"].fillna("")):
        m = url_pat.search(str(link))
        if m:
            lats.append(float(m.group(1))); lngs.append(float(m.group(2))); continue
        formula = maps_formulas[i] if i < len(maps_formulas) else ""
        m2 = url_pat.search(formula) or hyp_pat.search(formula)
        if m2:
            lats.append(float(m2.group(1))); lngs.append(float(m2.group(2)))
        else:
            lats.append(None); lngs.append(None)
    df["lat"], df["lng"] = lats, lngs

    # NORMALIZAR: números y NaN coherentes (evita error Folium)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")

    return df

# ========= UTILS MAPA =========
def _jitter(idx: int, base: float = 0.00008) -> float:
    random.seed(idx)
    return (random.random() - 0.5) * base

def _legend_html() -> str:
    items = "".join(
        f'<div style="display:flex;align-items:flex-start;margin-bottom:6px">'
        f'<span style="width:12px;height:12px;background:{FACTOR_COLORS[f]};'
        f'display:inline-block;margin-right:8px;border:1px solid #333;"></span>'
        f'<span style="font-size:12px;color:#000;line-height:1.2;">{f}</span></div>'
        for f in FACTORES
    )
    return (
        '<div style="position: fixed; bottom: 20px; right: 20px; z-index:9999; '
        'background: rgba(255,255,255,0.98); padding:10px; border:1px solid #666; '
        'border-radius:6px; max-height:320px; overflow:auto; width:340px; color:#000;">'
        '<div style="font-weight:700; margin-bottom:6px; color:#000;">Leyenda – Factores</div>'
        f'{items}</div>'
    )

# ========= UI =========
st.title("📍 Microdespliegue Pavas – Encuestas georreferenciadas")
tabs = st.tabs(["📝 Formulario", "🗺️ Mapa & Datos"])

# ======= FORM =======
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
            folium.CircleMarker([clicked["lat"], clicked["lng"]], radius=8, color="#000",
                                weight=1, fill=True, fill_color="#2dd4bf", fill_opacity=0.9,
                                tooltip="Ubicación seleccionada").add_to(m)
        map_ret = st_folium(m, height=520, use_container_width=True)
        if map_ret and map_ret.get("last_clicked"):
            st.session_state["clicked"] = {
                "lat": round(map_ret["last_clicked"]["lat"], 6),
                "lng": round(map_ret["last_clicked"]["lng"], 6),
            }
            clicked = st.session_state["clicked"]
        cols = st.columns(3)
        lat_val, lng_val = clicked.get("lat"), clicked.get("lng")
        cols[0].metric("Latitud", lat_val if lat_val is not None else "—")
        cols[1].metric("Longitud", lng_val if lng_val is not None else "—")
        if cols[2].button("Limpiar selección"):
            st.session_state.pop("clicked", None); st.rerun()

    with right:
        st.subheader("Formulario de encuesta")
        with st.form("form_encuesta", clear_on_submit=True):
            barrio = st.text_input("Barrio *")
            factor_sel = st.selectbox("Factor de riesgo *", options=FACTORES, index=None,
                                      placeholder="Selecciona un factor")
            delitos = st.text_area("Delitos relacionados al factor *", height=70)
            ligado = st.radio("Ligado a estructura criminal *", ["No", "Sí"], index=0, horizontal=True)
            nombre_estructura = st.text_input("Nombre de la estructura ligada (si aplica)")
            observ = st.text_area("Observaciones", height=90)
            submit = st.form_submit_button("Guardar en Google Sheets")

        if submit:
            errs = []
            if not barrio.strip(): errs.append("Indica el **Barrio**.")
            if not factor_sel: errs.append("Selecciona un **factor de riesgo**.")
            if not delitos.strip(): errs.append("Indica los **delitos relacionados**.")
            if lat_val is None or lng_val is None: errs.append("Selecciona un **punto en el mapa**.")
            if errs:
                st.error("• " + "\n• ".join(errs))
            else:
                data = {
                    "date": datetime.now(TZ).strftime("%d-%m-%Y"),
                    "barrio": barrio.strip(),
                    "factores": factor_sel,
                    "delitos_relacionados": delitos.strip(),
                    "ligado_estructura": ligado,
                    "nombre_estructura": nombre_estructura.strip(),
                    "observaciones": observ.strip(),
                    "lat": lat_val, "lng": lng_val,
                }
                try:
                    append_row(data)
                    st.success("✅ Respuesta guardada correctamente en Google Sheets.")
                except Exception as e:
                    st.error(f"❌ No se pudo guardar en Google Sheets.\n\n{e}")

# ======= MAPA & DATOS =======
with tabs[1]:
    st.subheader("Mapa interactivo + Tabla y administración")
    df = read_df()
    if df.empty:
        st.info("Aún no hay registros.")
    else:
        # Filtro por factor
        factores_unicos = [f for f in FACTORES if f in set(df["factores"].dropna().tolist())]
        filtro = st.selectbox("Mostrar solo factor", options=["(Todos)"] + factores_unicos, index=0)

        # Mapa
        m2 = folium.Map(location=[9.948, -84.144], zoom_start=13, control_scale=True)
        LocateControl(auto_start=False).add_to(m2)
        cluster = MarkerCluster().add_to(m2)
        m2.get_root().html.add_child(folium.Element(_legend_html()))

        idx = 0
        omitidos = 0
        for _, r in df.iterrows():
            lat, lng = r.get("lat"), r.get("lng")
            # Evitar NaNs/None
            if lat is None or lng is None or pd.isna(lat) or pd.isna(lng):
                omitidos += 1
                continue
            factor = str(r.get("factores","")).strip()
            if filtro != "(Todos)" and factor != filtro:
                continue
            color = FACTOR_COLORS.get(factor, "#555555")
            jlat = float(lat) + _jitter(idx); jlng = float(lng) + _jitter(idx+101)
            popup = folium.Popup(
                html=(f"<b>Fecha:</b> {r.get('date','')}<br>"
                      f"<b>Barrio:</b> {r.get('barrio','')}<br>"
                      f"<b>Factor:</b> {factor}<br>"
                      f"<b>Delitos:</b> {r.get('delitos_relacionados','')}<br>"
                      f"<b>Estructura:</b> {r.get('ligado_estructura','')} {r.get('nombre_estructura','')}<br>"
                      f"<b>Obs:</b> {r.get('observaciones','')}"),
                max_width=350,
            )
            folium.CircleMarker([jlat, jlng], radius=8, color="#000", weight=1,
                                fill=True, fill_color=color, fill_opacity=0.95,
                                popup=popup).add_to(cluster)
            idx += 1

        st_folium(m2, height=540, use_container_width=True)
        if omitidos:
            st.caption(f"({omitidos} registro(s) omitidos por coordenadas inválidas)")

        # Tabla (sin lat/lng visibles)
        show_df = df[["date","barrio","factores","delitos_relacionados",
                      "ligado_estructura","nombre_estructura","observaciones","maps_link"]]
        st.markdown("#### Tabla de respuestas")
        st.dataframe(show_df, use_container_width=True)
        st.download_button("⬇️ Descargar CSV",
                           data=show_df.to_csv(index=False).encode("utf-8"),
                           file_name="encuestas_pavas.csv", mime="text/csv")

        # ---- ADMIN: Eliminar ----
        st.markdown("---"); st.markdown("### 🗑️ Eliminar respuestas")
        ws = _ws()
        opciones = []
        for i, row in df.reset_index(drop=True).iterrows():
            opciones.append(f"{i+2}: {row.get('date','')} | {row.get('barrio','')} | {row.get('factores','')[:60]}")
        c1,c2 = st.columns([0.65,0.35])
        with c1:
            a_borrar = st.multiselect("Selecciona fila(s) (número inicial):", opciones)
        with c2:
            ok = st.checkbox("Confirmo eliminar seleccionadas")
            if st.button("Eliminar seleccionadas"):
                if not a_borrar: st.warning("No seleccionaste filas.")
                elif not ok: st.warning("Marca la casilla de confirmación.")
                else:
                    filas = sorted([int(x.split(":")[0]) for x in a_borrar], reverse=True)
                    try:
                        for f in filas: ws.delete_rows(f)
                        st.success(f"Eliminadas {len(filas)} fila(s). Recarga para ver cambios.")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"No se pudo eliminar: {e}")

        c3,c4 = st.columns([0.65,0.35])
        with c3:
            st.caption("Vaciar todo borra **todas** las respuestas (mantiene los encabezados).")
        with c4:
            ok2 = st.checkbox("Confirmo vaciar toda la hoja")
            if st.button("Vaciar todo"):
                if not ok2:
                    st.warning("Marca la casilla de confirmación.")
                else:
                    try:
                        total = len(ws.get_all_values())
                        if total > 1: ws.delete_rows(2, total)
                        st.success("Hoja vaciada. Recarga para ver cambios.")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"No se pudo vaciar: {e}")









