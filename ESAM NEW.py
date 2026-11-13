from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import os
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st
import plotly.express as px

# =========================================================
# 0. ZONA HORARIA LOCAL (EL SERVIDOR TRABAJA EN UTC)
# =========================================================
# El servidor (Streamlit Cloud / Neon) usa UTC. A partir de la noche, en UTC
# ya es el día siguiente y por eso las cargas quedaban con la fecha de mañana.
# Aquí se fija el desfase real del operador.
ZONA_HORARIA_UTC_OFFSET = -4  # Venezuela / Bolivia (UTC-4). Ajusta si cambias de país.


def ahora_local():
    """Fecha y hora local real del operador (UTC + desfase)."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=ZONA_HORARIA_UTC_OFFSET)


def hoy_local():
    """Fecha de HOY según la hora local del operador (nunca la del servidor)."""
    return ahora_local().date()


# =========================================================
# 0.1 UTILIDADES DE TIEMPO DE PARTIDO (HH:MM:SS)
# =========================================================
def parsear_tiempo_a_segundos(valor):
    """Convierte 'HH:MM:SS', 'MM:SS' o 'SS' a segundos. None si no es válido."""
    if valor is None or pd.isna(valor):
        return None
    texto_val = str(valor).strip()
    if not texto_val or texto_val.lower() in ("none", "nan", "nat", "null"):
        return None
    partes = texto_val.split(":")
    try:
        numeros = [int(float(p)) for p in partes]
    except ValueError:
        return None
    if len(numeros) == 3:
        horas, minutos, segundos = numeros
    elif len(numeros) == 2:
        horas, minutos, segundos = 0, numeros[0], numeros[1]
    elif len(numeros) == 1:
        horas, minutos, segundos = 0, 0, numeros[0]
    else:
        return None
    return horas * 3600 + minutos * 60 + segundos


def formatear_segundos(segundos):
    """Convierte segundos a texto HH:MM:SS legible."""
    if segundos is None:
        return "—"
    total = int(round(segundos))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


# =========================================================
# 1. CONFIGURACIÓN GENERAL DE LA PÁGINA Y ESTILOS VISUALES
# =========================================================
st.set_page_config(
    page_title="ESAM Analytics 360°",
    page_icon="💻",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');

/* ================= TOKENS ================= */
:root {
    --bg: #F6F8FC;
    --surface: #FFFFFF;
    --surface-2: #F1F5F9;
    --border: #E4EAF3;
    --border-strong: #D3DDEB;
    --text: #0F172A;
    --text-soft: #334155;
    --muted: #64748B;
    --accent: #2563EB;
    --accent-dark: #1D4ED8;
    --accent-soft: rgba(37, 99, 235, 0.08);
    --success: #0F9D6E;
    --r-sm: 8px;
    --r: 10px;
    --r-lg: 14px;
    --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
    --shadow: 0 1px 3px rgba(15, 23, 42, 0.06), 0 8px 24px -16px rgba(15, 23, 42, 0.24);
}

*, *::before, *::after { box-sizing: border-box; }

/* ================= BASE ================= */
html, body, [data-testid='stAppViewContainer'], [data-testid='stApp'] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
[data-testid='stHeader'] {
    background: rgba(246, 248, 252, 0.85) !important;
    backdrop-filter: blur(8px);
    border-bottom: 1px solid transparent !important;
}
[data-testid='stToolbar'] { right: 1rem !important; }

.block-container, [data-testid='stMainBlockContainer'] {
    padding-top: 2.4rem !important;
    padding-bottom: 4rem !important;
    max-width: 1320px !important;
}

/* ================= TIPOGRAFÍA ================= */
[data-testid='stMarkdownContainer'] p,
[data-testid='stMarkdownContainer'] li,
[data-testid='stCaptionContainer'],
label, input, textarea, button, select {
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif !important;
}
[data-testid='stMarkdownContainer'] p { color: var(--text-soft); line-height: 1.6; }

h1 {
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
    font-size: clamp(1.7rem, 2.4vw, 2.15rem) !important;
    font-weight: 800 !important;
    letter-spacing: -0.021em !important;
    line-height: 1.2 !important;
    color: var(--text) !important;
    padding: 0 0 0.9rem 0 !important;
    margin: 0 0 1rem 0 !important;
    border-bottom: 1px solid var(--border) !important;
}
h1 a { display: none !important; }

h2 {
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
    font-size: 1.3rem !important;
    font-weight: 700 !important;
    letter-spacing: -0.015em !important;
    color: var(--text) !important;
    margin: 1.8rem 0 0.6rem 0 !important;
    padding-bottom: 0 !important;
}
h2 a { display: none !important; }

h3 {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    font-weight: 600 !important;
    letter-spacing: 0 !important;
    color: var(--text) !important;
    margin: 1.5rem 0 0.55rem 0 !important;
    padding: 0 0 0 0.7rem !important;
    border-left: 3px solid var(--accent) !important;
    box-shadow: none !important;
    text-transform: none !important;
}
h3 a { display: none !important; }

h4, h5 {
    font-family: 'Inter', sans-serif !important;
    color: var(--text) !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
}

[data-testid='stCaptionContainer'] { color: var(--muted) !important; }
[data-testid='stCaptionContainer'] p { color: var(--muted) !important; font-size: 0.82rem !important; }

hr {
    border: none !important;
    height: 1px !important;
    background: var(--border) !important;
    margin: 1.8rem 0 !important;
}
a { color: var(--accent) !important; text-decoration: none; }
a:hover { text-decoration: underline; }
strong { color: var(--text); font-weight: 600; }

/* ================= SIDEBAR ================= */
[data-testid='stSidebar'] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border) !important;
    box-shadow: none !important;
}
[data-testid='stSidebar'] > div { background: transparent !important; }
[data-testid='stSidebar'] * { color: var(--text-soft); }
[data-testid='stSidebar'] h1,
[data-testid='stSidebar'] h2,
[data-testid='stSidebar'] h3 {
    color: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
    border: none !important;
    box-shadow: none !important;
    padding-left: 0 !important;
    font-size: 0.95rem !important;
    margin: 0.6rem 0 !important;
}
[data-testid='stSidebar'] hr { margin: 1rem 0 !important; }

/* ================= ETIQUETAS ================= */
[data-testid='stWidgetLabel'] p,
.stRadio label p,
[data-testid='stCheckbox'] label p {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    color: var(--text-soft) !important;
    margin-bottom: 0.1rem !important;
}

/* ================= ENTRADAS ================= */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-testid='stDateInput'] input, [data-testid='stTimeInput'] input {
    background: var(--surface) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--r-sm) !important;
    color: var(--text) !important;
    font-size: 0.9rem !important;
    padding: 0.5rem 0.7rem !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus,
[data-testid='stDateInput'] input:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
    outline: none !important;
}
.stTextInput input::placeholder, .stNumberInput input::placeholder,
.stTextArea textarea::placeholder { color: #94A3B8 !important; }

[data-baseweb='input'], [data-baseweb='base-input'] {
    background: transparent !important;
    border-radius: var(--r-sm) !important;
}

/* Selects */
[data-baseweb='select'] > div {
    background: var(--surface) !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--r-sm) !important;
    color: var(--text) !important;
    font-size: 0.9rem !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
[data-baseweb='select'] > div:hover { border-color: #B9C7DA !important; }
[data-baseweb='select'] > div:focus-within {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}
[data-baseweb='select'] svg { color: var(--muted) !important; }

/* Menús desplegables y calendarios */
[data-baseweb='popover'] [role='listbox'],
[data-baseweb='popover'] ul {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    box-shadow: 0 12px 32px -12px rgba(15, 23, 42, 0.28) !important;
    padding: 4px !important;
}
[data-baseweb='popover'] li,
[data-baseweb='menu'] li {
    background: transparent !important;
    color: var(--text-soft) !important;
    font-size: 0.88rem !important;
    border-radius: 6px !important;
}
[data-baseweb='popover'] li:hover,
[data-baseweb='menu'] li:hover { background: var(--surface-2) !important; color: var(--text) !important; }

[data-baseweb='calendar'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    color: var(--text) !important;
}
[data-baseweb='calendar'] * { color: var(--text-soft) !important; }
[data-baseweb='calendar'] [aria-selected='true'] {
    background: var(--accent) !important;
    color: #FFFFFF !important;
    border-radius: 6px !important;
}

/* ================= BOTONES ================= */
.stButton > button, [data-testid='stFormSubmitButton'] > button {
    width: 100%;
    background: var(--accent) !important;
    color: #FFFFFF !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    border: 1px solid var(--accent) !important;
    border-radius: var(--r-sm) !important;
    padding: 0.55rem 1rem !important;
    box-shadow: var(--shadow-sm) !important;
    transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease !important;
}
.stButton > button:hover, [data-testid='stFormSubmitButton'] > button:hover {
    background: var(--accent-dark) !important;
    border-color: var(--accent-dark) !important;
    transform: none !important;
    box-shadow: 0 6px 16px -6px rgba(37, 99, 235, 0.5) !important;
}
.stButton > button:active, [data-testid='stFormSubmitButton'] > button:active {
    transform: translateY(1px) !important;
}
.stButton > button:focus-visible { outline: 2px solid var(--accent) !important; outline-offset: 2px; }
.stButton > button:disabled, [data-testid='stFormSubmitButton'] > button:disabled {
    background: var(--surface-2) !important;
    color: #94A3B8 !important;
    border-color: var(--border) !important;
    box-shadow: none !important;
    opacity: 1 !important;
}

[data-testid='stDownloadButton'] > button {
    background: var(--surface) !important;
    color: var(--accent) !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.86rem !important;
    letter-spacing: 0 !important;
    border: 1px solid var(--border-strong) !important;
    border-radius: var(--r-sm) !important;
    padding: 0.5rem 1rem !important;
    box-shadow: var(--shadow-sm) !important;
    transition: background 0.15s ease, border-color 0.15s ease !important;
}
[data-testid='stDownloadButton'] > button:hover {
    background: var(--accent-soft) !important;
    border-color: var(--accent) !important;
    color: var(--accent-dark) !important;
}

/* ================= TARJETAS ================= */
[data-testid='stMetric'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-lg) !important;
    padding: 1rem 1.15rem !important;
    box-shadow: var(--shadow-sm) !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
[data-testid='stMetric']:hover {
    border-color: #CBD8EA !important;
    box-shadow: var(--shadow) !important;
    transform: none !important;
}
[data-testid='stMetricLabel'] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase !important;
    color: var(--muted) !important;
    white-space: normal !important;
}
[data-testid='stMetricLabel'] p { color: var(--muted) !important; }
[data-testid='stMetricValue'] {
    font-family: 'Plus Jakarta Sans', 'Inter', sans-serif !important;
    font-size: clamp(1.5rem, 2vw, 1.9rem) !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    color: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
    background: none !important;
    line-height: 1.2 !important;
}
[data-testid='stMetricDelta'] svg { display: none; }

[data-testid='stForm'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-lg) !important;
    padding: 1.35rem 1.4rem !important;
    box-shadow: var(--shadow-sm) !important;
}

[data-testid='stExpander'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    overflow: hidden !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid='stExpander'] details summary {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0 !important;
    color: var(--text) !important;
    padding: 0.25rem 0 !important;
}
[data-testid='stExpander'] details summary:hover { color: var(--accent) !important; }
[data-testid='stExpander'] details { border: none !important; }

[data-testid='stPlotlyChart'], [data-testid='stVegaLiteChart'],
[data-testid='stArrowVegaLiteChart'], [data-testid='stPyplot'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-lg) !important;
    padding: 0.5rem !important;
    box-shadow: var(--shadow-sm) !important;
}

/* ================= TABLAS ================= */
[data-testid='stDataFrame'], [data-testid='stTable'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    overflow: hidden !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid='stDataFrame'] * { font-family: 'Inter', sans-serif !important; }

/* ================= PESTAÑAS ================= */
.stTabs [data-baseweb='tab-list'] {
    background: var(--surface-2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    padding: 4px !important;
    gap: 4px !important;
}
.stTabs [data-baseweb='tab'] {
    background: transparent !important;
    color: var(--muted) !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.87rem !important;
    letter-spacing: 0 !important;
    border-radius: 7px !important;
    border: none !important;
    padding: 0.42rem 0.95rem !important;
    transition: color 0.15s ease, background 0.15s ease !important;
}
.stTabs [data-baseweb='tab']:hover { color: var(--text) !important; background: rgba(255, 255, 255, 0.7) !important; }
.stTabs [aria-selected='true'] {
    background: var(--surface) !important;
    color: var(--text) !important;
    box-shadow: var(--shadow-sm) !important;
}
.stTabs [data-baseweb='tab-highlight'], .stTabs [data-baseweb='tab-border'] { display: none !important; }
.stTabs [data-baseweb='tab'] p { color: inherit !important; opacity: 1 !important; }

/* ================= AVISOS ================= */
[data-testid='stAlert'] {
    border-radius: var(--r) !important;
    border-width: 1px !important;
    padding: 0.8rem 1rem !important;
}
[data-testid='stAlert'] p { font-size: 0.88rem !important; line-height: 1.5 !important; }

/* ================= CONTROLES ================= */
[data-testid='stCheckbox'] label, .stRadio label { color: var(--text-soft) !important; }
[data-testid='stCheckbox'] [data-baseweb='checkbox'] span { border-color: var(--border-strong) !important; }
.stRadio [role='radiogroup'] label { color: var(--text-soft) !important; }
[data-testid='stSlider'] [data-baseweb='slider'] div[role='slider'] { background-color: var(--accent) !important; }

/* ================= SCROLL ================= */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: #CDD8E6;
    border-radius: 8px;
    border: 2px solid var(--bg);
}
::-webkit-scrollbar-thumb:hover { background: #B3C2D4; }

/* ================= LIMPIEZA ================= */
#MainMenu, footer, [data-testid='stDecoration'], [data-testid='stStatusWidget'] { display: none !important; }

/* ================= PANTALLA DE ACCESO ================= */
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) {
    padding-top: 5rem !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) h1 {
    text-align: center;
    font-size: clamp(1.9rem, 3vw, 2.5rem) !important;
    letter-spacing: -0.025em !important;
    border-bottom: none !important;
    margin-bottom: 0.25rem !important;
    padding-bottom: 0 !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stMarkdownContainer'] p {
    text-align: center !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    font-size: 0.95rem !important;
    color: var(--muted) !important;
    margin-bottom: 1.8rem !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stTabs'] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: 18px !important;
    padding: 1.15rem 1.25rem 1.5rem !important;
    max-width: 520px !important;
    margin: 0 auto !important;
    box-shadow: 0 24px 60px -32px rgba(15, 23, 42, 0.35), var(--shadow-sm) !important;
    backdrop-filter: none !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stForm'] {
    border: none !important;
    box-shadow: none !important;
    padding: 0.35rem 0 0 !important;
    background: transparent !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stAlert'] p {
    text-align: left !important;
    text-transform: none !important;
    letter-spacing: 0 !important;
    font-size: 0.88rem !important;
    color: inherit !important;
    margin-bottom: 0 !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) h3 {
    border-left: none !important;
    padding-left: 0 !important;
    text-align: center !important;
    font-size: 0.95rem !important;
    color: var(--muted) !important;
    margin-top: 0.2rem !important;
}

/* Texto legible sobre botones */
.stButton button p,
[data-testid='stFormSubmitButton'] button p {
    color: #FFFFFF !important;
    opacity: 1 !important;
    font-weight: 600 !important;
    letter-spacing: 0 !important;
    text-transform: none !important;
    font-size: 0.88rem !important;
}
[data-testid='stDownloadButton'] button p {
    color: inherit !important;
    opacity: 1 !important;
    font-weight: 600 !important;
}
.stTabs [aria-selected='true'] p { color: var(--text) !important; opacity: 1 !important; }

/* ================= RESPONSIVE ================= */
@media (max-width: 900px) {
    .block-container, [data-testid='stMainBlockContainer'] {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1.5rem !important;
    }
    h1 { font-size: 1.5rem !important; }
    [data-testid='stMetric'] { padding: 0.8rem 0.9rem !important; }
    [data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) { padding-top: 2.5rem !important; }
}

/* =========================================================
   ESAM ANALYTICS 360° — ACTUALIZACIÓN VISUAL
   Cambios exclusivamente CSS: no modifica la lógica del sistema.
   ========================================================= */
:root {
    --bg: #F3F6FB;
    --surface: #FFFFFF;
    --surface-2: #F5F8FD;
    --border: #E3EAF4;
    --border-strong: #CBD6E5;
    --text: #101B33;
    --text-soft: #40516D;
    --muted: #74839B;
    --accent: #315FEA;
    --accent-dark: #2349C5;
    --accent-soft: rgba(49, 95, 234, 0.10);
    --success: #0E9F82;
    --r-sm: 10px;
    --r: 14px;
    --r-lg: 18px;
    --shadow-sm: 0 2px 8px rgba(24, 42, 76, 0.045);
    --shadow: 0 12px 30px rgba(24, 42, 76, 0.075);
}

/* Fondo y área de trabajo */
[data-testid='stAppViewContainer'],
[data-testid='stApp'] {
    background:
        radial-gradient(ellipse at 8% 0%, rgba(49,95,234,.055), transparent 34%),
        var(--bg) !important;
}
.block-container, [data-testid='stMainBlockContainer'] {
    max-width: 1450px !important;
    padding-top: 2rem !important;
    padding-bottom: 3.5rem !important;
}

/* Barra superior limpia */
[data-testid='stHeader'] {
    background: rgba(243,246,251,.88) !important;
    backdrop-filter: blur(14px);
    border-bottom: 1px solid rgba(227,234,244,.8) !important;
}

/* Navegación lateral: aspecto de panel de control */
[data-testid='stSidebar'] {
    background: linear-gradient(180deg, #111D36 0%, #172746 100%) !important;
    border-right: 1px solid #243656 !important;
    box-shadow: 8px 0 28px rgba(15,29,54,.08) !important;
}
[data-testid='stSidebar'] > div { background: transparent !important; }
[data-testid='stSidebar'] *,
[data-testid='stSidebar'] p,
[data-testid='stSidebar'] label,
[data-testid='stSidebar'] span {
    color: #DCE6F7 !important;
}
[data-testid='stSidebar'] h1,
[data-testid='stSidebar'] h2,
[data-testid='stSidebar'] h3 {
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}
[data-testid='stSidebar'] hr {
    border-color: rgba(220,230,247,.16) !important;
    background: rgba(220,230,247,.16) !important;
}
[data-testid='stSidebar'] [data-testid='stWidgetLabel'] p {
    color: #AFC0DA !important;
}
[data-testid='stSidebar'] [data-baseweb='select'] > div,
[data-testid='stSidebar'] input {
    background: #223452 !important;
    border-color: #344968 !important;
    color: #FFFFFF !important;
}
[data-testid='stSidebar'] [data-baseweb='select'] * {
    color: #FFFFFF !important;
}
[data-testid='stSidebar'] .stRadio [role='radiogroup'] label {
    background: rgba(255,255,255,.045);
    border: 1px solid rgba(255,255,255,.055);
    border-radius: 10px;
    padding: 8px 11px;
    margin: 3px 0;
    transition: background .18s ease, border-color .18s ease;
}
[data-testid='stSidebar'] .stRadio [role='radiogroup'] label:hover {
    background: rgba(255,255,255,.11);
    border-color: rgba(145,176,255,.35);
}

/* Jerarquía tipográfica */
h1 {
    font-size: clamp(1.8rem, 2.6vw, 2.35rem) !important;
    letter-spacing: -.035em !important;
    padding-bottom: .85rem !important;
    border-bottom: 1px solid var(--border) !important;
}
h2 {
    font-size: 1.32rem !important;
    letter-spacing: -.025em !important;
    margin-top: 1.65rem !important;
}
h3 {
    font-size: .98rem !important;
    border-left: 3px solid #5478F2 !important;
    padding-left: .75rem !important;
}

/* Campos y selectores */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-testid='stDateInput'] input, [data-testid='stTimeInput'] input,
[data-baseweb='select'] > div {
    min-height: 42px;
    border-radius: 10px !important;
    border-color: #D5DFEC !important;
    background: #FFFFFF !important;
}
.stTextInput input:focus, .stNumberInput input:focus,
.stTextArea textarea:focus, [data-testid='stDateInput'] input:focus,
[data-testid='stTimeInput'] input:focus {
    border-color: #5478F2 !important;
    box-shadow: 0 0 0 3px rgba(49,95,234,.12) !important;
}

/* Botones con relieve sutil */
.stButton > button, [data-testid='stFormSubmitButton'] > button {
    min-height: 42px;
    border-radius: 10px !important;
    background: linear-gradient(135deg, #3868F0 0%, #2853D8 100%) !important;
    border: 1px solid #315FEA !important;
    box-shadow: 0 4px 10px rgba(49,95,234,.16) !important;
    font-weight: 650 !important;
}
.stButton > button:hover, [data-testid='stFormSubmitButton'] > button:hover {
    background: linear-gradient(135deg, #2F5DE5 0%, #2048C5 100%) !important;
    box-shadow: 0 7px 16px rgba(49,95,234,.22) !important;
    transform: translateY(-1px) !important;
}
[data-testid='stDownloadButton'] > button {
    min-height: 42px;
    border-radius: 10px !important;
}

/* Métricas y contenedores */
[data-testid='stMetric'] {
    border: 1px solid #E3EAF4 !important;
    border-radius: 16px !important;
    padding: 1.1rem 1.2rem !important;
    background: linear-gradient(145deg, #FFFFFF 0%, #FBFCFF 100%) !important;
    box-shadow: 0 4px 14px rgba(24,42,76,.045) !important;
}
[data-testid='stMetric']:hover {
    border-color: #C9D6F2 !important;
    box-shadow: 0 10px 24px rgba(24,42,76,.08) !important;
}
[data-testid='stMetricLabel'] {
    font-size: .74rem !important;
    letter-spacing: .055em !important;
}
[data-testid='stMetricValue'] {
    font-size: clamp(1.55rem, 2.1vw, 2.05rem) !important;
    letter-spacing: -.04em !important;
}
[data-testid='stForm'],
[data-testid='stExpander'] {
    border: 1px solid var(--border) !important;
    border-radius: 15px !important;
    box-shadow: var(--shadow-sm) !important;
}
[data-testid='stForm'] {
    padding: 1.4rem !important;
}

/* Gráficos y tablas */
[data-testid='stPlotlyChart'], [data-testid='stVegaLiteChart'],
[data-testid='stArrowVegaLiteChart'], [data-testid='stPyplot'],
[data-testid='stDataFrame'], [data-testid='stTable'] {
    border: 1px solid var(--border) !important;
    border-radius: 15px !important;
    box-shadow: var(--shadow-sm) !important;
    background: #FFFFFF !important;
}
[data-testid='stDataFrame'] {
    padding: 3px !important;
}

/* Pestañas */
.stTabs [data-baseweb='tab-list'] {
    border-radius: 12px !important;
    padding: 5px !important;
    background: #EAF0F9 !important;
}
.stTabs [data-baseweb='tab'] {
    border-radius: 9px !important;
    padding: .5rem 1rem !important;
}
.stTabs [aria-selected='true'] {
    background: #FFFFFF !important;
    color: #244CCB !important;
    box-shadow: 0 2px 7px rgba(24,42,76,.08) !important;
}

/* Alertas y detalles */
[data-testid='stAlert'] {
    border-radius: 12px !important;
}
[data-testid='stExpander'] details summary {
    padding: .45rem .15rem !important;
}
::-webkit-scrollbar-thumb {
    background: #BFCBE0 !important;
    border: 2px solid var(--bg) !important;
}

/* Adaptación a pantallas pequeñas */
@media (max-width: 768px) {
    .block-container, [data-testid='stMainBlockContainer'] {
        padding: 1.15rem .85rem 2.5rem !important;
    }
    [data-testid='stMetric'] {
        padding: .85rem !important;
    }
    h1 {
        font-size: 1.65rem !important;
    }
}


/* =========================================================
   ESAM ANALYTICS 360° — TEMA OSCURO
   Fondo negro/grafito y superficies oscuras.
   ========================================================= */
:root {
    --bg: #080B12;
    --surface: #111722;
    --surface-2: #171F2D;
    --border: #263247;
    --border-strong: #35445D;
    --text: #F1F5FC;
    --text-soft: #C2CCDC;
    --muted: #91A0B7;
    --accent: #5B83FF;
    --accent-dark: #3F66E8;
    --accent-soft: rgba(91, 131, 255, 0.16);
    --shadow-sm: 0 3px 12px rgba(0, 0, 0, 0.22);
    --shadow: 0 12px 30px rgba(0, 0, 0, 0.30);
}

html, body,
[data-testid='stApp'],
[data-testid='stAppViewContainer'],
[data-testid='stMain'],
[data-testid='stMainBlockContainer'] {
    background: #080B12 !important;
    color: #F1F5FC !important;
}
[data-testid='stAppViewContainer'] {
    background:
        radial-gradient(ellipse at 12% 0%, rgba(65, 99, 190, .13), transparent 38%),
        #080B12 !important;
}
.block-container, [data-testid='stMainBlockContainer'] {
    color: #F1F5FC !important;
}

/* Texto general */
.stMarkdown, .stText, p, li, label,
[data-testid='stWidgetLabel'],
[data-testid='stMarkdownContainer'] {
    color: #DCE5F3;
}
h1, h2, h3, h4, h5, h6 {
    color: #F7F9FD !important;
    -webkit-text-fill-color: #F7F9FD !important;
    border-color: #263247 !important;
}
small, [data-testid='stCaptionContainer'] {
    color: #91A0B7 !important;
}

/* Cabecera y navegación */
[data-testid='stHeader'] {
    background: rgba(8, 11, 18, .92) !important;
    border-bottom: 1px solid #202B3D !important;
}
[data-testid='stSidebar'] {
    background: linear-gradient(180deg, #070A11 0%, #10192A 100%) !important;
    border-right: 1px solid #263247 !important;
}
[data-testid='stSidebar'] > div {
    background: transparent !important;
}

/* Tarjetas, formularios, expanders y contenedores */
[data-testid='stMetric'],
[data-testid='stForm'],
[data-testid='stExpander'],
[data-testid='stPlotlyChart'],
[data-testid='stVegaLiteChart'],
[data-testid='stArrowVegaLiteChart'],
[data-testid='stPyplot'],
[data-testid='stDataFrame'],
[data-testid='stTable'],
div[data-testid='stVerticalBlockBorderWrapper'] {
    background: #111722 !important;
    color: #F1F5FC !important;
    border-color: #263247 !important;
    box-shadow: 0 5px 18px rgba(0,0,0,.22) !important;
}
[data-testid='stMetric'] {
    background: linear-gradient(145deg, #151E2C 0%, #101722 100%) !important;
}
[data-testid='stMetricLabel'],
[data-testid='stMetricValue'],
[data-testid='stMetricDelta'] {
    color: #F1F5FC !important;
}
[data-testid='stExpander'] details,
[data-testid='stExpander'] summary {
    background: #111722 !important;
    color: #E8EEF8 !important;
}

/* Campos de entrada */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-testid='stDateInput'] input, [data-testid='stTimeInput'] input,
[data-baseweb='select'] > div,
[data-baseweb='input'] > div {
    background: #171F2D !important;
    color: #F1F5FC !important;
    border-color: #35445D !important;
    caret-color: #8EAAFF !important;
}
input, textarea {
    color: #F1F5FC !important;
}
input::placeholder, textarea::placeholder {
    color: #8796AD !important;
    opacity: 1 !important;
}
[data-baseweb='select'] *,
[data-baseweb='popover'] *,
[role='listbox'] *,
[role='option'] {
    color: #EAF0FA !important;
}
[data-baseweb='popover'],
[role='listbox'] {
    background: #171F2D !important;
    border: 1px solid #35445D !important;
}
[data-baseweb='select'] svg {
    fill: #C2CCDC !important;
}

/* Botones */
.stButton > button,
[data-testid='stFormSubmitButton'] > button,
[data-testid='stDownloadButton'] > button {
    color: #FFFFFF !important;
}
.stButton > button[kind='secondary'],
button[kind='secondary'] {
    background: #1B2638 !important;
    border-color: #35445D !important;
}

/* Pestañas */
.stTabs [data-baseweb='tab-list'] {
    background: #111722 !important;
    border: 1px solid #263247 !important;
}
.stTabs [data-baseweb='tab'] {
    color: #B9C6DA !important;
}
.stTabs [aria-selected='true'] {
    background: #263653 !important;
    color: #FFFFFF !important;
}

/* Tablas */
[data-testid='stDataFrame'] *,
[data-testid='stTable'] * {
    color: #E5ECF7 !important;
}
[data-testid='stDataFrame'] [role='grid'],
[data-testid='stDataFrame'] [role='row'],
[data-testid='stDataFrame'] [role='columnheader'] {
    background: #111722 !important;
}

/* Alertas */
[data-testid='stAlert'] {
    background: #151F30 !important;
    border-color: #35445D !important;
    color: #EAF0FA !important;
}
hr {
    border-color: #263247 !important;
}

/* Barra de desplazamiento */
::-webkit-scrollbar-track {
    background: #080B12 !important;
}
::-webkit-scrollbar-thumb {
    background: #35445D !important;
    border: 2px solid #080B12 !important;
}



/* Marcadores: ajustar etiquetas, cifras y variaciones al ancho de cada tarjeta */
div[data-testid="stMetric"] {
    min-width: 0 !important;
    max-width: 100% !important;
    overflow: hidden !important;
}
div[data-testid="stMetricLabel"] {
    min-width: 0 !important;
    font-size: clamp(0.60rem, 0.78vw, 0.74rem) !important;
    line-height: 1.18 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}
div[data-testid="stMetricValue"] {
    min-width: 0 !important;
    max-width: 100% !important;
    font-size: clamp(0.78rem, 1.05vw, 1.02rem) !important;
    line-height: 1.10 !important;
    letter-spacing: -0.04em !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
}
div[data-testid="stMetricValue"] > div {
    min-width: 0 !important;
    max-width: 100% !important;
    font-size: inherit !important;
    line-height: inherit !important;
    white-space: inherit !important;
    overflow-wrap: inherit !important;
    word-break: inherit !important;
}
div[data-testid="stMetricDelta"] {
    min-width: 0 !important;
    font-size: clamp(0.56rem, 0.70vw, 0.66rem) !important;
    line-height: 1.12 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}
div[data-testid="stMetricDelta"] svg {
    width: 0.65rem !important;
    height: 0.65rem !important;
}
@media (max-width: 900px) {
    div[data-testid="stMetricValue"] { font-size: 0.86rem !important; }
}
@media (max-width: 640px) {
    div[data-testid="stMetric"] { padding: 0.52rem !important; }
    div[data-testid="stMetricLabel"],
    div[data-testid="stMetricDelta"] { font-size: 0.58rem !important; }
    div[data-testid="stMetricValue"] { font-size: 0.78rem !important; }
}


/* =========================================================
   AJUSTES SOLICITADOS: COLORES, ACCESO Y MARCADORES
   ========================================================= */

/* Paleta más viva sin alterar la estructura de los módulos */
:root {
    --accent: #397BFF;
    --accent-dark: #245CEB;
    --accent-soft: rgba(57, 123, 255, .20);
    --success: #16C784;
}
[data-testid='stAppViewContainer'] {
    background:
      radial-gradient(ellipse at 8% 0%, rgba(42,111,255,.20), transparent 35%),
      radial-gradient(ellipse at 95% 12%, rgba(0,204,170,.09), transparent 30%),
      #080B12 !important;
}
[data-testid='stSidebar'] {
    background: linear-gradient(180deg, #09152B 0%, #10264A 55%, #101B32 100%) !important;
    border-right: 1px solid #294878 !important;
}
.stButton > button, [data-testid='stFormSubmitButton'] > button {
    background: linear-gradient(135deg, #4387FF 0%, #2458F0 100%) !important;
    border: 1px solid #5793FF !important;
    box-shadow: 0 5px 16px rgba(37,99,235,.30) !important;
}
.stButton > button:hover, [data-testid='stFormSubmitButton'] > button:hover {
    background: linear-gradient(135deg, #5A98FF 0%, #3269FF 100%) !important;
    box-shadow: 0 7px 20px rgba(37,99,235,.42) !important;
}

/* Inicio: panel compacto, centrado y con jerarquía visual */
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) {
    max-width: 560px !important;
    padding-top: 2.0rem !important;
    padding-bottom: 2rem !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) h1 {
    font-size: clamp(1.65rem, 3vw, 2.15rem) !important;
    line-height: 1.12 !important;
    margin-bottom: .35rem !important;
    background: linear-gradient(90deg, #FFFFFF 0%, #9FC4FF 55%, #54E4D0 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stMarkdownContainer'] p {
    font-size: .84rem !important;
    line-height: 1.4 !important;
    margin-bottom: 1rem !important;
    color: #AFC3E2 !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stTabs'] {
    max-width: 440px !important;
    padding: .85rem 1rem 1rem !important;
    border: 1px solid #30496F !important;
    border-radius: 17px !important;
    background: linear-gradient(145deg, #17243A 0%, #101A2B 100%) !important;
    box-shadow: 0 18px 48px rgba(0,0,0,.38), 0 0 0 1px rgba(74,132,255,.08) !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stForm'] {
    padding: .15rem 0 0 !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) h3 {
    font-size: .88rem !important;
    margin: .1rem 0 .65rem !important;
    color: #C5D7F2 !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) .stTextInput input {
    min-height: 40px !important;
    background: #0D1728 !important;
    border: 1px solid #385477 !important;
    border-radius: 9px !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) .stButton > button,
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stFormSubmitButton'] > button {
    min-height: 40px !important;
    margin-top: .35rem !important;
    font-size: .9rem !important;
    border-radius: 9px !important;
}
[data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) .stTabs [data-baseweb='tab-list'] {
    margin-bottom: .55rem !important;
}

/* Marcadores: cifras mayores, legibles y contenidas en cada tarjeta */
div[data-testid="stMetric"] {
    min-width: 0 !important;
    max-width: 100% !important;
    overflow: hidden !important;
    padding: .9rem .95rem !important;
    border: 1px solid #304767 !important;
    background: linear-gradient(145deg, #18263B 0%, #111B2B 100%) !important;
}
div[data-testid="stMetricLabel"] {
    font-size: clamp(.68rem, .85vw, .80rem) !important;
    line-height: 1.2 !important;
    color: #AFC5E8 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
}
div[data-testid="stMetricValue"] {
    min-width: 0 !important;
    max-width: 100% !important;
    font-size: clamp(1.05rem, 1.55vw, 1.48rem) !important;
    font-weight: 800 !important;
    line-height: 1.14 !important;
    letter-spacing: -.035em !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
}
div[data-testid="stMetricValue"] > div,
div[data-testid="stMetricValue"] [data-testid="stMarkdownContainer"] {
    min-width: 0 !important;
    max-width: 100% !important;
    font-size: inherit !important;
    line-height: inherit !important;
    overflow-wrap: anywhere !important;
    word-break: break-word !important;
}
div[data-testid="stMetricDelta"] {
    font-size: clamp(.62rem, .75vw, .72rem) !important;
    line-height: 1.15 !important;
    overflow-wrap: anywhere !important;
}
@media (max-width: 1100px) {
    div[data-testid="stMetricValue"] { font-size: clamp(.98rem, 1.7vw, 1.25rem) !important; }
}
@media (max-width: 640px) {
    [data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) {
        padding: 1.2rem .75rem 1.5rem !important;
    }
    [data-testid='stMainBlockContainer']:has(h1[style*='text-align: center']) [data-testid='stTabs'] {
        padding: .7rem .75rem .85rem !important;
    }
    div[data-testid="stMetric"] { padding: .65rem !important; }
    div[data-testid="stMetricValue"] { font-size: 1rem !important; }
}


/* =========================================================
   REDISEÑO FINAL — COLORES VIVOS + ACCESO CENTRADO
   Solo presentación; conserva intacta la lógica del programa.
   ========================================================= */
:root {
  --bg: #090F1F;
  --surface: #121D35;
  --surface-2: #1A2A49;
  --border: #2A416C;
  --border-strong: #4266A5;
  --text: #F5F8FF;
  --text-soft: #D5E2FA;
  --muted: #9DB2D8;
  --accent: #00D4FF;
  --accent-dark: #087DFF;
  --accent-soft: rgba(0,212,255,.18);
  --success: #35E6A2;
}
html, body, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {
  background: #090F1F !important;
  color: #F5F8FF !important;
}
[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(ellipse at 12% 0%, rgba(0,212,255,.20), transparent 34%),
    radial-gradient(ellipse at 92% 18%, rgba(126,87,255,.20), transparent 32%),
    linear-gradient(145deg,#080D1B 0%,#0D1830 55%,#10152B 100%) !important;
}
[data-testid="stHeader"] { background: rgba(8,13,27,.92) !important; }
.block-container, [data-testid="stMainBlockContainer"] {
  max-width: 1480px !important;
  padding-top: 1.35rem !important;
}
[data-testid="stSidebar"] {
  background: linear-gradient(180deg,#101D3B 0%,#172B55 52%,#241B50 100%) !important;
  border-right: 1px solid rgba(0,212,255,.28) !important;
}
[data-testid="stSidebar"] * { color: #EAF4FF !important; }
[data-testid="stSidebar"] h2 { color:#FFFFFF !important; }
/* Acciones con colores eléctricos */
.stButton > button, .stFormSubmitButton > button, button[kind="primary"] {
  background: linear-gradient(105deg,#087DFF 0%,#00BDEB 52%,#7657FF 100%) !important;
  color:#FFFFFF !important; border:0 !important; border-radius:12px !important;
  font-weight:800 !important; box-shadow:0 7px 22px rgba(0,160,255,.27) !important;
  transition:transform .15s ease, filter .15s ease !important;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
  filter:brightness(1.15) saturate(1.2) !important; transform:translateY(-1px) !important;
}
[data-testid="stMetric"] {
  background:linear-gradient(145deg,#172B50 0%,#14213D 55%,#211C4C 100%) !important;
  border:1px solid rgba(0,212,255,.38) !important;
  border-radius:16px !important; box-shadow:0 9px 26px rgba(0,0,0,.22), inset 0 1px 0 rgba(255,255,255,.06) !important;
}
[data-testid="stMetricLabel"] { color:#A9DFFF !important; }
[data-testid="stMetricValue"] { color:#FFFFFF !important; -webkit-text-fill-color:#FFFFFF !important; }
[data-testid="stTabs"] [role="tab"] { color:#C7D8F4 !important; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color:#FFFFFF !important; border-bottom-color:#00D4FF !important;
}
input, textarea, [data-baseweb="select"] > div {
  background:#101D36 !important; color:#FFFFFF !important;
  border-color:#36588C !important; border-radius:10px !important;
}
label, [data-testid="stWidgetLabel"], .stMarkdown p, .stMarkdown li { color:#D9E6FA !important; }
/* Pantalla de acceso: ancho limitado, centrada y con marca siempre visible */
[data-testid="stMainBlockContainer"]:has(.login-brand) {
  max-width:760px !important; width:calc(100% - 2rem) !important;
  margin:0 auto !important; padding:2.1rem 1.25rem 2.8rem !important;
}
.login-brand { text-align:center; margin:0 auto 1.15rem; padding:.25rem .5rem .2rem; }
.login-brand-icon {
  width:54px;height:54px;margin:0 auto .7rem;border-radius:16px;
  display:flex;align-items:center;justify-content:center;
  color:#061326;font-size:1rem;font-weight:1000;letter-spacing:-.06em;
  background:linear-gradient(135deg,#00E5FF,#5B7CFF 58%,#A36BFF);
  box-shadow:0 8px 28px rgba(0,190,255,.3);
}
.login-brand-name {
  color:#FFFFFF !important; font-size:clamp(1.55rem,4vw,2.25rem);
  line-height:1.1;font-weight:900;letter-spacing:.025em;
  text-shadow:0 3px 24px rgba(0,190,255,.2);
}
.login-brand-name span { color:#00D9FF !important; }
.login-brand-subtitle {
  margin-top:.55rem;color:#AFC6E9 !important;font-size:.68rem;
  font-weight:800;letter-spacing:.16em;line-height:1.5;
}
.login-brand-line {
  width:94px;height:3px;margin:1rem auto 0;border-radius:4px;
  background:linear-gradient(90deg,#087DFF,#00E5FF,#946BFF);
}
[data-testid="stMainBlockContainer"]:has(.login-brand) [data-testid="stTabs"] {
  background:linear-gradient(145deg,rgba(24,43,77,.98),rgba(20,29,57,.98)) !important;
  border:1px solid rgba(0,212,255,.28) !important;border-radius:20px !important;
  padding:1.15rem 1.4rem 1.4rem !important;
  box-shadow:0 18px 48px rgba(0,0,0,.32),inset 0 1px 0 rgba(255,255,255,.06) !important;
}
[data-testid="stMainBlockContainer"]:has(.login-brand) [data-testid="stTabs"] [role="tablist"] {
  justify-content:center;gap:.6rem;border-bottom:1px solid #2A416C !important;
}
[data-testid="stMainBlockContainer"]:has(.login-brand) [data-testid="stTabs"] [role="tab"] {
  padding:.65rem 1rem !important;font-weight:800 !important;
}
[data-testid="stMainBlockContainer"]:has(.login-brand) h2,
[data-testid="stMainBlockContainer"]:has(.login-brand) h3 {
  color:#FFFFFF !important;text-align:center !important;font-size:1.12rem !important;
  margin:.8rem 0 1rem !important;
}
[data-testid="stMainBlockContainer"]:has(.login-brand) [data-testid="stForm"] {
  border:0 !important;background:transparent !important;padding:.15rem .15rem .2rem !important;
}
[data-testid="stMainBlockContainer"]:has(.login-brand) .stFormSubmitButton > button {
  min-height:2.85rem !important;margin-top:.55rem !important;
}
@media(max-width:640px) {
  [data-testid="stMainBlockContainer"]:has(.login-brand) {
    width:100% !important;padding:1.1rem .65rem 1.5rem !important;
  }
  [data-testid="stMainBlockContainer"]:has(.login-brand) [data-testid="stTabs"] {
    padding:.8rem .65rem 1rem !important;
  }
  .login-brand-subtitle { font-size:.58rem;letter-spacing:.1em; }
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# 2. SEGURIDAD Y ENCRIPTACIÓN (PBKDF2-SHA256 CON SAL)
# =========================================================
PBKDF2_ITERACIONES = 240_000


def hash_password(password: str) -> str:
    """Hash con sal aleatoria: pbkdf2_sha256$iteraciones$sal$hash."""
    sal = os.urandom(16)
    digesto = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, PBKDF2_ITERACIONES)
    return f"pbkdf2_sha256${PBKDF2_ITERACIONES}${sal.hex()}${digesto.hex()}"


def verificar_password(password: str, hash_guardado) -> bool:
    """Verifica la clave contra el hash nuevo (con sal) o el viejo SHA-256."""
    if not hash_guardado:
        return False
    guardado = str(hash_guardado)
    if guardado.startswith("pbkdf2_sha256$"):
        try:
            _, iteraciones, sal_hex, digesto_hex = guardado.split("$")
            digesto = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(sal_hex), int(iteraciones)
            )
            return hmac.compare_digest(digesto.hex(), digesto_hex)
        except Exception:
            return False
    # Compatibilidad con el hash antiguo (SHA-256 sin sal), se migra al iniciar sesión
    return hmac.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), guardado)


def hash_es_legado(hash_guardado) -> bool:
    """True si el hash guardado es del esquema viejo (sin sal) o está vacío."""
    return not str(hash_guardado or "").startswith("pbkdf2_sha256$")


def _secreto(clave, defecto=None):
    try:
        if clave in st.secrets:
            return st.secrets[clave]
    except Exception:
        pass
    return defecto


# Contraseña inicial del admin. Puedes fijarla en st.secrets con: admin_password = "..."
ADMIN_PASSWORD_INICIAL = _secreto("admin_password", "admin123")

# Aviso único si las tarifas no se pueden leer de la base de datos
AVISO_TASAS_MOSTRADO = {"visto": False}


# =========================================================
# 3. CONEXIÓN A BASE DE DATOS (NEON POSTGRESQL)
# =========================================================
def get_db_connection():
    try:
        if "postgres" not in st.secrets or "url" not in st.secrets["postgres"]:
            st.error("❌ Error de configuración: La clave '[postgres]' o 'url' no existe en los secretos de Streamlit.")
            return None
        return psycopg2.connect(st.secrets["postgres"]["url"])
    except Exception as e:
        st.error(f"❌ Error de conexión a Neon PostgreSQL: {e}")
        return None


def cerrar_conexion(conn):
    """Cierra la conexión sin romper la app si ya estaba cerrada."""
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


# =========================================================
# 4. INICIALIZACIÓN Y MIGRACIÓN AUTOMÁTICA DE TABLAS
# =========================================================
# =========================================================
# 4. INICIALIZACIÓN Y MIGRACIÓN AUTOMÁTICA DE TABLAS
# =========================================================
def init_db():
    """Crea y migra las tablas.

    Usa autocommit: cada sentencia queda guardada al ejecutarse, así un ALTER
    que falle no deshace el CREATE TABLE (ese rollback era el que dejaba la
    base sin tabla 'usuarios').
    """
    conn = get_db_connection()
    if not conn:
        return False

    cur = None
    try:
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                nombre VARCHAR(100) NOT NULL DEFAULT 'Operador',
                password_hash VARCHAR(200) NOT NULL DEFAULT '',
                password VARCHAR(100),
                rol VARCHAR(30) DEFAULT 'operador',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Columnas que pueden faltar en bases creadas con versiones anteriores
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nombre VARCHAR(100) DEFAULT 'Operador';")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password_hash VARCHAR(200) DEFAULT '';")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS password VARCHAR(100);")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS rol VARCHAR(30) DEFAULT 'operador';")
        cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
        cur.execute("ALTER TABLE usuarios ALTER COLUMN password DROP NOT NULL;")
        cur.execute("ALTER TABLE usuarios ALTER COLUMN password_hash TYPE VARCHAR(200);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS partidos (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                codigo_partido VARCHAR(50) NOT NULL,
                fecha DATE NOT NULL,
                tiempo_ejecucion VARCHAR(30),
                tarifa NUMERIC(10, 2) DEFAULT 0.00,
                tipo_partido VARCHAR(30) DEFAULT 'quincenal',
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS picheos (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                fecha DATE NOT NULL,
                id_control VARCHAR(50) NOT NULL,
                cantidad INTEGER NOT NULL,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_global (
                clave VARCHAR(50) PRIMARY KEY,
                valor NUMERIC(10, 4) NOT NULL
            );
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_partidos_usuario_fecha ON partidos (usuario_id, fecha);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_partidos_fecha ON partidos (fecha);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picheos_usuario_fecha ON picheos (usuario_id, fecha);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_picheos_fecha ON picheos (fecha);")

        defaults = [
            ("tasa_tramo_1", 6.00),
            ("tasa_tramo_2", 6.50),
            ("tasa_tramo_3", 7.00),
            ("tasa_tramo_4", 7.50),
            ("tasa_tramo_5", 8.00),
            ("tasa_en_vivo_normal", 12.00),
            ("tasa_en_vivo_nba", 18.50),
            ("precio_beisbol", 0.024),
        ]
        for clave, val in defaults:
            cur.execute("""
                INSERT INTO configuracion_global (clave, valor)
                VALUES (%s, %s)
                ON CONFLICT (clave) DO NOTHING;
            """, (clave, val))

        # Migración única al esquema de 5 tramos de básquetbol
        cur.execute("SELECT valor FROM configuracion_global WHERE clave = 'esquema_tramos_basket';")
        if cur.fetchone() is None:
            tramos_nuevos = [
                ("tasa_tramo_1", 6.00),
                ("tasa_tramo_2", 6.50),
                ("tasa_tramo_3", 7.00),
                ("tasa_tramo_4", 7.50),
                ("tasa_tramo_5", 8.00),
            ]
            for clave_t, val_t in tramos_nuevos:
                cur.execute("""
                    INSERT INTO configuracion_global (clave, valor)
                    VALUES (%s, %s)
                    ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor;
                """, (clave_t, val_t))
            cur.execute("""
                INSERT INTO configuracion_global (clave, valor)
                VALUES ('esquema_tramos_basket', 2)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor;
            """)

        # El admin se crea una sola vez: no se resetea la clave en cada arranque
        cur.execute("""
            INSERT INTO usuarios (username, nombre, password_hash, rol)
            VALUES ('admin', 'Administrador Global', %s, 'admin')
            ON CONFLICT (username) DO NOTHING;
        """, (hash_password(ADMIN_PASSWORD_INICIAL),))

        return True
    except Exception as e:
        st.error(f"❌ Error al inicializar tablas: {e}")
        return False
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        cerrar_conexion(conn)


# Sin @st.cache_resource: si falla, reintenta en la próxima recarga
if not st.session_state.get("_db_iniciada"):
    st.session_state["_db_iniciada"] = init_db()


# =========================================================
# 5. CONSULTAS OPTIMIZADAS Y RECÁLCULO RETROACTIVO ESTRICTO
# =========================================================
@st.cache_data(ttl=5)
def obtener_tasas_globales():
    tasas = {
        "tramo_1": 6.00,
        "tramo_2": 6.50,
        "tramo_3": 7.00,
        "tramo_4": 7.50,
        "tramo_5": 8.00,
        "en_vivo_normal": 12.00,
        "en_vivo_nba": 18.50,
        "precio_beisbol": 0.024,
    }
    conn = get_db_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT clave, valor FROM configuracion_global;")
            for r in cur.fetchall():
                k = r["clave"]
                val = float(r["valor"])
                if k == "tasa_tramo_1": tasas["tramo_1"] = val
                elif k == "tasa_tramo_2": tasas["tramo_2"] = val
                elif k == "tasa_tramo_3": tasas["tramo_3"] = val
                elif k == "tasa_tramo_4": tasas["tramo_4"] = val
                elif k == "tasa_tramo_5": tasas["tramo_5"] = val
                elif k == "tasa_en_vivo_normal": tasas["en_vivo_normal"] = val
                elif k == "tasa_en_vivo_nba": tasas["en_vivo_nba"] = val
                elif k == "precio_beisbol": tasas["precio_beisbol"] = val
        except Exception as e:
            # No se oculta el fallo: sin BD se estarían usando precios de fábrica
            if not AVISO_TASAS_MOSTRADO["visto"]:
                AVISO_TASAS_MOSTRADO["visto"] = True
                st.warning(f"⚠️ No se pudieron leer las tarifas de la base de datos ({e}). Se muestran las de fábrica.")
        finally:
            try:
                if cur is not None: cur.close()
            except Exception:
                pass
            cerrar_conexion(conn)
    return tasas


def actualizar_tasa_global(clave, nuevo_valor):
    """Solo la cuenta administradora puede modificar las tarifas globales."""
    info_sesion = st.session_state.get("user_info") or {}
    usuario_sesion = str(info_sesion.get("username", "")).lower().strip()
    if not st.session_state.get("authenticated", False) or usuario_sesion != "admin":
        st.error("⛔ No tienes permisos para modificar los montos. Solo el administrador puede hacerlo.")
        return False

    conn = get_db_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("UPDATE configuracion_global SET valor = %s WHERE clave = %s;", (nuevo_valor, clave))
            conn.commit()
            st.cache_data.clear()
            return True
        except Exception as e:
            conn.rollback()
            st.error(f"Error al actualizar tasa: {e}")
            return False
        finally:
            try:
                if cur is not None: cur.close()
            except Exception:
                pass
            cerrar_conexion(conn)
    return False


def obtener_tarifa_basket(tipo_partido, cant_partidos=0):
    tasas = obtener_tasas_globales()
    if tipo_partido == "en_vivo_nba":
        return tasas["en_vivo_nba"]
    elif tipo_partido == "en_vivo_normal":
        return tasas["en_vivo_normal"]
    else:
        if cant_partidos <= 11: return tasas["tramo_1"]
        elif cant_partidos <= 14: return tasas["tramo_2"]
        elif cant_partidos <= 26: return tasas["tramo_3"]
        elif cant_partidos <= 29: return tasas["tramo_4"]
        else: return tasas["tramo_5"]


def recalcular_tarifas_quincena_basket(u_id, fecha_ref):
    """
    1. Cuenta EXCLUSIVAMENTE los partidos de modalidad 'quincenal' en la quincena dada.
    2. Los partidos 'en_vivo_normal' y 'en_vivo_nba' NO CUENTAN para el volumen del tramo.
    3. Actualiza RETROACTIVAMENTE solo la tarifa de los partidos 'quincenal' al tramo correspondiente.
    """
    iq_i, iq_f = obtener_rango_quincena(fecha_ref)
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            
            # Si u_id es 0 (Consolidado Admin), recalcula para cada usuario individualmente
            if u_id == 0:
                cur.execute("SELECT id FROM usuarios;")
                usuarios_list = [r[0] for r in cur.fetchall()]
                for uid in usuarios_list:
                    recalcular_tarifas_quincena_basket(uid, fecha_ref)
                cur.close()
                conn.close()
                return

            # Contar ÚNICAMENTE partidos de modalidad 'quincenal' (los en vivo no suman)
            cur.execute("""
                SELECT COUNT(*) FROM partidos 
                WHERE usuario_id = %s 
                  AND fecha >= %s 
                  AND fecha <= %s 
                  AND (tipo_partido IS NULL OR tipo_partido = 'quincenal');
            """, (u_id, iq_i, iq_f))
            partidos_quincenales_contados = cur.fetchone()[0]

            # Determinar la tarifa del tramo alcanzado
            nueva_tarifa = obtener_tarifa_basket("quincenal", partidos_quincenales_contados)

            # Actualizar ÚNICAMENTE la tarifa de los partidos de modalidad 'quincenal'
            cur.execute("""
                UPDATE partidos 
                SET tarifa = %s 
                WHERE usuario_id = %s 
                  AND fecha >= %s 
                  AND fecha <= %s 
                  AND (tipo_partido IS NULL OR tipo_partido = 'quincenal');
            """, (nueva_tarifa, u_id, iq_i, iq_f))

            conn.commit()
        except Exception as e:
            st.error(f"Error al recalcular quincena: {e}")
        finally:
            try:
                cur.close()
            except Exception:
                pass
            cerrar_conexion(conn)


def recalcular_si_hace_falta(u_id, fecha_ref):
    """Recalcula la quincena una sola vez por sesión (evita consultas en cada clic)."""
    iq_i, iq_f = obtener_rango_quincena(fecha_ref)
    hechos = st.session_state.setdefault("_recalculos_hechos", set())
    clave = f"{u_id}|{iq_i}|{iq_f}"
    if clave in hechos:
        return
    recalcular_tarifas_quincena_basket(u_id, fecha_ref)
    hechos.add(clave)


def olvidar_recalculos():
    """Fuerza a recalcular en la próxima vista (tras cambiar datos o precios)."""
    st.session_state["_recalculos_hechos"] = set()


# =========================================================
# 6. GESTIÓN DE USUARIOS Y FECHAS DE QUINCENA
# =========================================================
def registrar_usuario(username, nombre, password, rol="operador"):
    conn = get_db_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO usuarios (username, nombre, password_hash, rol)
                VALUES (%s, %s, %s, %s);
            """, (username.lower().strip(), nombre.strip(), hash_password(password), rol))
            conn.commit()
            st.cache_data.clear()
            return True, "✅ Usuario registrado exitosamente."
        except psycopg2.IntegrityError:
            conn.rollback()
            return False, "⚠️ El nombre de usuario ya existe."
        except Exception as e:
            conn.rollback()
            return False, f"❌ Error en registro: {e}"
        finally:
            try:
                if cur is not None: cur.close()
            except Exception:
                pass
            cerrar_conexion(conn)
    return False, "❌ Error de conexión a BD."


def autenticar_usuario(username, password):
    """Valida la clave en Python y migra el hash viejo en el mismo inicio de sesión."""
    user_clean = username.lower().strip()
    pass_clean = password.strip()

    conn = get_db_connection()
    if not conn:
        return None

    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("""
                SELECT id, username, nombre, rol, password_hash, password
                FROM usuarios WHERE username = %s;
            """, (user_clean,))
            fila = cur.fetchone()
        except Exception:
            # Bases antiguas sin columna 'password'
            conn.rollback()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT id, username, nombre, rol, password_hash
                FROM usuarios WHERE username = %s;
            """, (user_clean,))
            fila = cur.fetchone()

        if not fila:
            return None

        clave_plana = fila.get("password")
        coincide = verificar_password(pass_clean, fila.get("password_hash"))
        if not coincide and clave_plana and hmac.compare_digest(str(clave_plana), pass_clean):
            coincide = True
        if not coincide:
            return None

        # Migración silenciosa: pasa de SHA-256/plano a PBKDF2 con sal
        if hash_es_legado(fila.get("password_hash")) or clave_plana:
            try:
                cur.execute(
                    "UPDATE usuarios SET password_hash = %s, password = NULL WHERE id = %s;",
                    (hash_password(pass_clean), fila["id"]),
                )
                conn.commit()
            except Exception:
                conn.rollback()

        return {"id": fila["id"], "username": fila["username"], "nombre": fila["nombre"], "rol": fila["rol"]}
    except Exception as e:
        st.error(f"Error al autenticar: {e}")
        return None
    finally:
        try:
            if cur is not None: cur.close()
        except Exception:
            pass
        cerrar_conexion(conn)


def cambiar_password_usuario(user_id, nueva_password):
    conn = get_db_connection()
    if conn:
        cur = None
        try:
            cur = conn.cursor()
            nuevo_hash = hash_password(nueva_password)
            try:
                cur.execute(
                    "UPDATE usuarios SET password_hash = %s, password = NULL WHERE id = %s;",
                    (nuevo_hash, user_id),
                )
            except Exception:
                conn.rollback()
                cur = conn.cursor()
                cur.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s;", (nuevo_hash, user_id))
            conn.commit()
            return True, "✅ Contraseña actualizada correctamente."
        except Exception as e:
            conn.rollback()
            return False, f"❌ Error al actualizar contraseña: {e}"
        finally:
            try:
                if cur is not None: cur.close()
            except Exception:
                pass
            cerrar_conexion(conn)
    return False, "❌ Error de conexión a BD."


@st.cache_data(ttl=5)
def obtener_todos_los_usuarios():
    conn = get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT u.id, u.username, u.nombre, u.rol,
                   COUNT(DISTINCT p.id) as total_partidos_basket,
                   COUNT(DISTINCT pi.id) as total_picheos_beisbol
            FROM usuarios u
            LEFT JOIN partidos p ON u.id = p.usuario_id
            LEFT JOIN picheos pi ON u.id = pi.usuario_id
            GROUP BY u.id, u.username, u.nombre, u.rol
            ORDER BY u.id ASC;
        """
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        st.error(f"Error al cargar usuarios: {e}")
        return pd.DataFrame()
    finally:
        cerrar_conexion(conn)


def obtener_rango_quincena(fecha_ref, numero_quincena=None):
    anio = fecha_ref.year
    mes = fecha_ref.month
    
    if numero_quincena == 1:
        return date(anio, mes, 1), date(anio, mes, 15)
    elif numero_quincena == 2:
        if mes == 12:
            fin_mes = date(anio, 12, 31)
        else:
            fin_mes = date(anio, mes + 1, 1) - timedelta(days=1)
        return date(anio, mes, 16), fin_mes
    else:
        if fecha_ref.day <= 15:
            return date(anio, mes, 1), date(anio, mes, 15)
        else:
            if mes == 12:
                fin_mes = date(anio, 12, 31)
            else:
                fin_mes = date(anio, mes + 1, 1) - timedelta(days=1)
            return date(anio, mes, 16), fin_mes


RANGOS_PERIODO = [
    "Todos los Registros",
    "1. 1.ª Quincena (Días 1 al 15)",
    "2. 2.ª Quincena (Días 16 al final de mes)",
    "Quincena Anterior",
    "Este Mes Completo",
    "Rango de Fechas Personalizado",
]


def selector_periodo(clave, titulo):
    """Dibuja el filtro de quincena/periodo y devuelve (fecha_inicio, fecha_fin)."""
    hoy = hoy_local()
    seleccion = st.sidebar.selectbox(titulo, RANGOS_PERIODO, key=clave)

    if "1. 1.ª Quincena" in seleccion:
        return obtener_rango_quincena(hoy, numero_quincena=1)
    if "2. 2.ª Quincena" in seleccion:
        return obtener_rango_quincena(hoy, numero_quincena=2)
    if seleccion == "Quincena Anterior":
        if hoy.day <= 15:
            primer_dia_mes_actual = date(hoy.year, hoy.month, 1)
            ultimo_dia_mes_pasado = primer_dia_mes_actual - timedelta(days=1)
            return obtener_rango_quincena(ultimo_dia_mes_pasado, numero_quincena=2)
        return obtener_rango_quincena(hoy, numero_quincena=1)
    if seleccion == "Este Mes Completo":
        fin_mes = date(hoy.year, 12, 31) if hoy.month == 12 else date(hoy.year, hoy.month + 1, 1) - timedelta(days=1)
        return date(hoy.year, hoy.month, 1), fin_mes
    if seleccion == "Rango de Fechas Personalizado":
        col_desde, col_hasta = st.sidebar.columns(2)
        with col_desde:
            f_ini = st.date_input("Desde", value=hoy - timedelta(days=30), key=f"{clave}_desde")
        with col_hasta:
            f_fin = st.date_input("Hasta", value=hoy, key=f"{clave}_hasta")
        if f_ini > f_fin:
            st.sidebar.warning("⚠️ 'Desde' es posterior a 'Hasta'. Se invirtieron las fechas.")
            f_ini, f_fin = f_fin, f_ini
        return f_ini, f_fin
    return date(2020, 1, 1), date(2035, 12, 31)


# =========================================================
# 7. MANEJO DE SESIÓN Y AUTENTICACIÓN
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if not st.session_state.authenticated:
    st.markdown("""
        <div class="login-brand">
            <div class="login-brand-icon">ESAM</div>
            <div class="login-brand-name">ESAM ANALYTICS <span>360°</span></div>
            <div class="login-brand-subtitle">CENTRO DE CONTROL · ESTADÍSTICAS Y OPERACIONES</div>
            <div class="login-brand-line"></div>
        </div>
    """, unsafe_allow_html=True)

    tab_login, tab_registro = st.tabs(["🔐  Iniciar sesión", "＋  Crear cuenta"])

    with tab_login:
        st.subheader("Ingreso de Operadores")
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            submit_login = st.form_submit_button("Entrar al Sistema", use_container_width=True)

            if submit_login:
                if user_input and pass_input:
                    user_data = autenticar_usuario(user_input, pass_input)
                    if user_data:
                        st.session_state.authenticated = True
                        st.session_state.user_info = user_data
                        st.success(f"Bienvenido/a, {user_data['nombre']}")
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.")
                else:
                    st.warning("Complete todos los campos.")

    with tab_registro:
        st.subheader("Crear Cuenta de Operador")
        with st.form("form_registro"):
            reg_name = st.text_input("Nombre Completo")
            reg_user = st.text_input("Nombre de Usuario")
            reg_pass1 = st.text_input("Contraseña", type="password")
            reg_pass2 = st.text_input("Confirmar Contraseña", type="password")
            submit_reg = st.form_submit_button("Registrar Cuenta", use_container_width=True)

            if submit_reg:
                if not (reg_name and reg_user and reg_pass1 and reg_pass2):
                    st.warning("Todos los campos son obligatorios.")
                elif reg_pass1 != reg_pass2:
                    st.error("Las contraseñas no coinciden.")
                elif len(reg_pass1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    exito, msg = registrar_usuario(reg_user, reg_name, reg_pass1, "operador")
                    if exito: st.success(msg)
                    else: st.error(msg)

else:
    # =========================================================
    # PANEL PRINCIPAL Y NAVEGACIÓN PRIVADA
    # =========================================================
    user_id = st.session_state.user_info["id"]
    user_name = st.session_state.user_info["nombre"]
    username_actual = st.session_state.user_info["username"].lower().strip()
    rol_actual = st.session_state.user_info.get("rol", "operador")

    es_admin_estricto = (username_actual == "admin")

    st.sidebar.markdown("""
        <div style='text-align: left; padding: 2px 0 12px 0;'>
            <h2 style='color: #0F172A; margin: 0 0 3px 0; font-family: "Plus Jakarta Sans", Inter, sans-serif; font-size: 1.02rem; font-weight: 700; letter-spacing: -0.015em;'>💻 ESAM Analytics</h2>
            <p style='color: #64748B; font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600; margin: 0;'>360° Stats Pro</p>
        </div>
    """, unsafe_allow_html=True)
    
    st.sidebar.write(f"👤 **Analista:** {user_name}")
    
    opciones_menu_list = [
        "📊 Panel General y Estadísticas",
        "🏀 Módulo Básquetbol",
        "⚾ Módulo Béisbol",
        "🔐 Seguridad y Contraseñas"
    ]
    
    if es_admin_estricto:
        opciones_menu_list.insert(3, "⚙️ Administración de Precios por Deporte")

    st.sidebar.markdown("---")
    opcion_menu = st.sidebar.radio("🧭 Menú Principal:", opciones_menu_list)

    st.sidebar.markdown("---")
    
    if es_admin_estricto:
        modo_super_admin = st.sidebar.checkbox("👑 Activar Modo Admin Global", value=True)
        es_admin = modo_super_admin
    else:
        es_admin = False

    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

    # =========================================================
    # MÓDULO: PANTALLA PRINCIPAL
    # =========================================================
    if opcion_menu == "📊 Panel General y Estadísticas":
        st.title("📊 Panel General y Análisis Estadístico 360°")
        
        target_user_id = user_id
        opcion_label = f"mis datos ({user_name})"

        if es_admin:
            df_usrs = obtener_todos_los_usuarios()
            if not df_usrs.empty:
                opciones_u = {"🌐 CONSOLIDADO GLOBAL (TODOS LOS USUARIOS)": 0}
                for _, r_u in df_usrs.iterrows():
                    opciones_u[f"👤 {r_u['nombre']} (@{r_u['username']})"] = r_u['id']
                
                st.sidebar.markdown("---")
                st.sidebar.subheader("👑 Selector de Analista")
                u_seleccionado = st.sidebar.selectbox("Ver Panel General de:", list(opciones_u.keys()))
                target_user_id = opciones_u[u_seleccionado]
                opcion_label = u_seleccionado

        st.sidebar.markdown("---")
        st.sidebar.subheader("🔍 Filtro por Quincena y Periodo")

        f_ini, f_fin = selector_periodo("gen_periodo", "Seleccionar Periodo:")

        # Recálculo automático de quincena (una sola vez por sesión)
        recalcular_si_hace_falta(target_user_id, f_ini)

        st.caption(f"Mostrando análisis operativo de: **{opcion_label}** | Periodo: **{f_ini.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')}**")

        df_b_all = pd.DataFrame()
        df_beis_all = pd.DataFrame()
        conn_gen = get_db_connection()
        total_g_basket = 0.0
        total_g_beisbol = 0.0
        total_juegos_b = 0
        total_lotes_beisbol = 0
        total_pich_b = 0
        tiempo_promedio_seg = None
        juegos_con_tiempo = 0

        if conn_gen:
            try:
                if target_user_id == 0:
                    df_b_all = pd.read_sql_query("SELECT tarifa, tiempo_ejecucion, fecha FROM partidos WHERE fecha BETWEEN %s AND %s;", conn_gen, params=(f_ini, f_fin))
                    df_beis_all = pd.read_sql_query("SELECT cantidad, fecha FROM picheos WHERE fecha BETWEEN %s AND %s;", conn_gen, params=(f_ini, f_fin))
                else:
                    df_b_all = pd.read_sql_query("SELECT tarifa, tiempo_ejecucion, fecha FROM partidos WHERE usuario_id = %s AND fecha BETWEEN %s AND %s;", conn_gen, params=(target_user_id, f_ini, f_fin))
                    df_beis_all = pd.read_sql_query("SELECT cantidad, fecha FROM picheos WHERE usuario_id = %s AND fecha BETWEEN %s AND %s;", conn_gen, params=(target_user_id, f_ini, f_fin))

                if not df_b_all.empty:
                    total_g_basket = float(df_b_all["tarifa"].sum())
                    total_juegos_b = len(df_b_all)

                    # Tiempo promedio real de los partidos cargados con tiempo
                    tiempos_b = [
                        t for t in (parsear_tiempo_a_segundos(v) for v in df_b_all["tiempo_ejecucion"])
                        if t is not None
                    ]
                    if tiempos_b:
                        tiempo_promedio_seg = sum(tiempos_b) / len(tiempos_b)
                        juegos_con_tiempo = len(tiempos_b)

                if not df_beis_all.empty:
                    total_pich_b = int(df_beis_all["cantidad"].sum())
                    total_lotes_beisbol = len(df_beis_all)
                    precio_b_u = obtener_tasas_globales()["precio_beisbol"]
                    total_g_beisbol = total_pich_b * precio_b_u

            except Exception as e:
                st.error(f"Error al calcular totales: {e}")
            finally:
                cerrar_conexion(conn_gen)

        total_ganancias_general = total_g_basket + total_g_beisbol
        total_registros_brutos = total_juegos_b + total_lotes_beisbol

        promedio_basket = (total_g_basket / total_juegos_b) if total_juegos_b > 0 else 0.00
        tasas_cur = obtener_tasas_globales()

        # TARJETAS PRINCIPALES
        col_mg1, col_mg2, col_mg3, col_mg4, col_mg5 = st.columns(5)
        col_mg1.metric("💰 Total Acumulado", f"${total_ganancias_general:,.2f}", "📈 Rendimiento Alza")
        col_mg2.metric("🏀 Básquetbol Total", f"${total_g_basket:,.2f}", f"🔺 {total_juegos_b} partidos")
        col_mg3.metric("⚾ Béisbol Total", f"${total_g_beisbol:,.2f}", f"🔺 {total_pich_b:,} picheos")
        col_mg4.metric("📊 Cargas Totales", f"{total_registros_brutos} ops", "🟢 Sistema Óptimo")
        col_mg5.metric("⏱️ Tiempo Promedio", formatear_segundos(tiempo_promedio_seg), f"⏱️ {juegos_con_tiempo} partidos con tiempo")

        st.markdown("---")
        
        # VISUALIZACIÓN GRÁFICA REAL
        col_g1, col_g2 = st.columns([1, 1])

        with col_g1:
            st.subheader("📊 Distribución de Ingresos por Deporte")
            if total_ganancias_general > 0:
                data_pie = pd.DataFrame({
                    'Deporte': ['Básquetbol', 'Béisbol'],
                    'Ingresos': [total_g_basket, total_g_beisbol]
                })
                fig_pie = px.pie(data_pie, values='Ingresos', names='Deporte', 
                                 color_discrete_sequence=['#2563EB', '#14B8A6'],
                                 hole=0.4)
                fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font_color='#334155')
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Registra datos en Básquetbol o Béisbol para el periodo seleccionado para generar gráficos.")

        with col_g2:
            st.subheader("📈 Análisis y Desglose Operativo")
            df_desglose = pd.DataFrame({
                "Disciplina": ["🏀 Básquetbol", "⚾ Béisbol"],
                "Unidades Registradas": [f"{total_juegos_b} partidos", f"{total_pich_b:,} picheos"],
                "Promedio por Carga": [f"${promedio_basket:.2f} / partido", f"${tasas_cur['precio_beisbol']:.3f} / picheo"],
                "Total USD": [f"${total_g_basket:,.2f}", f"${total_g_beisbol:,.2f}"]
            })
            st.dataframe(df_desglose, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📈 Evolución Diaria del Periodo")
        series_diarias = []
        if not df_b_all.empty:
            tmp_b = df_b_all.copy()
            tmp_b["fecha"] = pd.to_datetime(tmp_b["fecha"])
            series_diarias.append(
                tmp_b.groupby("fecha").agg({"tarifa": "sum"}).rename(columns={"tarifa": "🏀 Básquetbol ($)"})
            )
        if not df_beis_all.empty:
            tmp_p = df_beis_all.copy()
            tmp_p["fecha"] = pd.to_datetime(tmp_p["fecha"])
            tmp_p["usd"] = tmp_p["cantidad"].astype(float) * tasas_cur["precio_beisbol"]
            series_diarias.append(
                tmp_p.groupby("fecha").agg({"usd": "sum"}).rename(columns={"usd": "⚾ Béisbol ($)"})
            )
        if series_diarias:
            df_serie = pd.concat(series_diarias, axis=1).fillna(0.0).sort_index()
            df_serie["Total ($)"] = df_serie.sum(axis=1)
            fig_serie = px.bar(
                df_serie,
                x=df_serie.index,
                y=[c for c in df_serie.columns if c != "Total ($)"],
                barmode="stack",
                color_discrete_sequence=["#2563EB", "#14B8A6"],
                labels={"value": "Ingresos (USD)", "x": "Fecha", "variable": "Deporte"},
            )
            fig_serie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#334155", legend_title_text="",
            )
            st.plotly_chart(fig_serie, use_container_width=True)
            st.caption(
                f"Mejor día: **${df_serie['Total ($)'].max():,.2f}** | "
                f"Días con actividad: **{len(df_serie)}** | "
                f"Promedio diario: **${df_serie['Total ($)'].mean():,.2f}**"
            )
        else:
            st.info("Sin movimientos en el periodo seleccionado para graficar la evolución.")

        # ---------------- DESCARGA DE CARGAS (RESPALDO POR RANGO) ----------------
        st.markdown("---")
        with st.expander("📦 Descargar cargas completas (cualquier periodo)"):
            st.caption(
                "Descarga los registros crudos de los dos deportes entre dos fechas, "
                "aunque no coincidan con el periodo elegido arriba. Sirve para guardar un "
                "respaldo o revisar un periodo viejo sin perder nada."
            )
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                dl_desde = st.date_input("Desde", value=f_ini, key="dl_cargas_desde")
            with col_dl2:
                dl_hasta = st.date_input("Hasta", value=f_fin, key="dl_cargas_hasta")
            if dl_desde > dl_hasta:
                st.warning("⚠️ 'Desde' es posterior a 'Hasta'. Se invirtieron las fechas.")
                dl_desde, dl_hasta = dl_hasta, dl_desde

            conn_dl = get_db_connection()
            if conn_dl:
                df_dl_b = pd.DataFrame()
                df_dl_p = pd.DataFrame()
                try:
                    if target_user_id == 0:
                        df_dl_b = pd.read_sql_query("""
                            SELECT p.id AS "ID", u.username AS "Usuario", u.nombre AS "Operador",
                                   p.codigo_partido AS "Código Partido", p.fecha AS "Fecha",
                                   p.tiempo_ejecucion AS "Tiempo Ejecución",
                                   p.tarifa AS "Tarifa USD", p.tipo_partido AS "Modalidad",
                                   p.creado_en AS "Registrado"
                            FROM partidos p
                            JOIN usuarios u ON u.id = p.usuario_id
                            WHERE p.fecha BETWEEN %s AND %s
                            ORDER BY p.fecha ASC, p.id ASC;
                        """, conn_dl, params=(dl_desde, dl_hasta))
                        df_dl_p = pd.read_sql_query("""
                            SELECT pi.id AS "ID", u.username AS "Usuario", u.nombre AS "Operador",
                                   pi.fecha AS "Fecha", pi.id_control AS "ID Control",
                                   pi.cantidad AS "Cantidad", pi.creado_en AS "Registrado"
                            FROM picheos pi
                            JOIN usuarios u ON u.id = pi.usuario_id
                            WHERE pi.fecha BETWEEN %s AND %s
                            ORDER BY pi.fecha ASC, pi.id ASC;
                        """, conn_dl, params=(dl_desde, dl_hasta))
                    else:
                        df_dl_b = pd.read_sql_query("""
                            SELECT p.id AS "ID", u.username AS "Usuario", u.nombre AS "Operador",
                                   p.codigo_partido AS "Código Partido", p.fecha AS "Fecha",
                                   p.tiempo_ejecucion AS "Tiempo Ejecución",
                                   p.tarifa AS "Tarifa USD", p.tipo_partido AS "Modalidad",
                                   p.creado_en AS "Registrado"
                            FROM partidos p
                            JOIN usuarios u ON u.id = p.usuario_id
                            WHERE p.usuario_id = %s AND p.fecha BETWEEN %s AND %s
                            ORDER BY p.fecha ASC, p.id ASC;
                        """, conn_dl, params=(target_user_id, dl_desde, dl_hasta))
                        df_dl_p = pd.read_sql_query("""
                            SELECT pi.id AS "ID", u.username AS "Usuario", u.nombre AS "Operador",
                                   pi.fecha AS "Fecha", pi.id_control AS "ID Control",
                                   pi.cantidad AS "Cantidad", pi.creado_en AS "Registrado"
                            FROM picheos pi
                            JOIN usuarios u ON u.id = pi.usuario_id
                            WHERE pi.usuario_id = %s AND pi.fecha BETWEEN %s AND %s
                            ORDER BY pi.fecha ASC, pi.id ASC;
                        """, conn_dl, params=(target_user_id, dl_desde, dl_hasta))
                except Exception as e:
                    st.error(f"❌ No se pudieron leer las cargas: {e}")
                finally:
                    cerrar_conexion(conn_dl)

                if not df_dl_p.empty:
                    df_dl_p["USD (precio actual)"] = (
                        df_dl_p["Cantidad"].astype(float) * float(tasas_cur["precio_beisbol"])
                    ).round(2)

                st.markdown(
                    f"**Básquetbol:** {len(df_dl_b)} partidos &nbsp;·&nbsp; "
                    f"**Béisbol:** {len(df_dl_p)} lotes de picheos"
                )
                c_dl1, c_dl2 = st.columns(2)
                with c_dl1:
                    st.download_button(
                        "📥 Descargar Partidos de Básquetbol (CSV)",
                        data=df_dl_b.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"esam_partidos_{dl_desde}_al_{dl_hasta}.csv",
                        mime="text/csv",
                        disabled=df_dl_b.empty,
                        use_container_width=True,
                        key="dl_cargas_partidos",
                    )
                with c_dl2:
                    st.download_button(
                        "📥 Descargar Picheos de Béisbol (CSV)",
                        data=df_dl_p.to_csv(index=False).encode("utf-8-sig"),
                        file_name=f"esam_picheos_{dl_desde}_al_{dl_hasta}.csv",
                        mime="text/csv",
                        disabled=df_dl_p.empty,
                        use_container_width=True,
                        key="dl_cargas_picheos",
                    )

        if es_admin and target_user_id == 0:
            st.markdown("---")
            st.subheader("👥 Auditoría General de Operadores en Sistema (Filtrado por Periodo)")
            conn_det = get_db_connection()
            if conn_det:
                try:
                    # Cada tabla se resume por operador ANTES de unirla.
                    # Así se evita que varios partidos x varios lotes de picheos
                    # multipliquen artificialmente las sumas.
                    df_det = pd.read_sql_query("""
                        WITH basket_por_usuario AS (
                            SELECT
                                usuario_id,
                                COUNT(*) AS partidos_basket,
                                COALESCE(SUM(tarifa), 0.00) AS usd_basket
                            FROM partidos
                            WHERE fecha BETWEEN %s AND %s
                            GROUP BY usuario_id
                        ),
                        beisbol_por_usuario AS (
                            SELECT
                                usuario_id,
                                COALESCE(SUM(cantidad), 0) AS total_picheos
                            FROM picheos
                            WHERE fecha BETWEEN %s AND %s
                            GROUP BY usuario_id
                        )
                        SELECT
                            u.id AS "ID",
                            u.username AS "Usuario",
                            u.nombre AS "Nombre Completo",
                            COALESCE(b.partidos_basket, 0) AS "Partidos Basket",
                            COALESCE(b.usd_basket, 0.00) AS "USD Basket",
                            COALESCE(pi.total_picheos, 0) AS "Total Picheos",
                            COALESCE(pi.total_picheos, 0) *
                                COALESCE((SELECT valor FROM configuracion_global
                                          WHERE clave = 'precio_beisbol'), 0) AS "USD Béisbol"
                        FROM usuarios u
                        LEFT JOIN basket_por_usuario b ON b.usuario_id = u.id
                        LEFT JOIN beisbol_por_usuario pi ON pi.usuario_id = u.id
                        ORDER BY u.id ASC;
                    """, conn_det, params=(f_ini, f_fin, f_ini, f_fin))
                    df_tiempos_det = pd.read_sql_query("""
                        SELECT u.id AS uid, p.tiempo_ejecucion
                        FROM usuarios u
                        JOIN partidos p ON u.id = p.usuario_id AND p.fecha BETWEEN %s AND %s;
                    """, conn_det, params=(f_ini, f_fin))

                    if not df_det.empty:
                        df_det["Ganancia Total ($)"] = df_det["USD Basket"] + df_det["USD Béisbol"]

                        promedios_t = {}
                        if not df_tiempos_det.empty:
                            for uid, grupo in df_tiempos_det.groupby("uid"):
                                segs = [
                                    t for t in (parsear_tiempo_a_segundos(v) for v in grupo["tiempo_ejecucion"])
                                    if t is not None
                                ]
                                promedios_t[uid] = formatear_segundos(sum(segs) / len(segs)) if segs else "—"
                        df_det["Tiempo Promedio"] = df_det["ID"].map(promedios_t).fillna("—")

                        st.dataframe(df_det, use_container_width=True, hide_index=True)

                        csv_det = df_det.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            "📥 Exportar Auditoría Consolidada (CSV)",
                            data=csv_det,
                            file_name=f"esam_auditoria_{f_ini}_al_{f_fin}.csv",
                            mime="text/csv",
                        )
                except Exception as e:
                    st.error(f"Error cargando detalle de usuarios: {e}")
                finally:
                    cerrar_conexion(conn_det)

    # =========================================================
    # MÓDULO 1: BÁSQUETBOL (RECÁLCULO RETROACTIVO GARANTIZADO)
    # =========================================================
    elif opcion_menu == "🏀 Módulo Básquetbol":
        st.title("🏀 ESAM Analytics — Módulo Básquetbol")
        
        target_b_user_id = user_id
        if es_admin:
            df_usrs = obtener_todos_los_usuarios()
            if not df_usrs.empty:
                opciones_b = {"🌐 CONSOLIDADO GLOBAL (TODOS LOS USUARIOS)": 0}
                for _, r_u in df_usrs.iterrows():
                    opciones_b[f"👤 {r_u['nombre']} (@{r_u['username']})"] = r_u['id']
                
                u_b_sel = st.sidebar.selectbox("👑 Ver Básquetbol de:", list(opciones_b.keys()))
                target_b_user_id = opciones_b[u_b_sel]

        st.caption("Control Financiero y Tiempos de Partidos por Quincena")

        st.sidebar.markdown("---")
        st.sidebar.subheader("🔍 Filtro por Quincena y Periodo")

        f_ini, f_fin = selector_periodo("basket_periodo", "Seleccionar Periodo:")

        # Recálculo automático de quincena (una sola vez por sesión)
        recalcular_si_hace_falta(target_b_user_id, f_ini)

        st.info(f"📅 **Periodo Evaluado:** Del **{f_ini.strftime('%d/%m/%Y')}** al **{f_fin.strftime('%d/%m/%Y')}**")

        with st.expander("➕ Registrar Nuevo Partido de Básquetbol", expanded=False):
            col_m1, _ = st.columns([2, 2])
            with col_m1:
                modalidad_sel = st.radio("Modalidad:", ["🏀 Quincenal Estándar", "⚡ En Vivo Normal", "🔥 En Vivo NBA"])

            cf1, cf2, cf3 = st.columns(3)
            with cf1: fecha_p = st.date_input("Fecha", value=hoy_local(), key="b_fecha")
            with cf2: codigo_p = st.text_input("Código de Partido", placeholder="Ej: 1042")
            with cf3: tiempo_p = st.text_input("Tiempo Ejecución", placeholder="HH:MM:SS")

            tasas_v = obtener_tasas_globales()
            if "NBA" in modalidad_sel:
                t_guardar = "en_vivo_nba"
                tarifa_calc = tasas_v["en_vivo_nba"]
            elif "Normal" in modalidad_sel:
                t_guardar = "en_vivo_normal"
                tarifa_calc = tasas_v["en_vivo_normal"]
            else:
                t_guardar = "quincenal"
                tarifa_calc = tasas_v["tramo_1"]

            if st.button("💾 Guardar Partido", use_container_width=True):
                tiempo_val = (tiempo_p or "").strip()
                segundos_t = parsear_tiempo_a_segundos(tiempo_val) if tiempo_val else None
                if not codigo_p.strip():
                    st.warning("Ingrese el código del partido.")
                elif tiempo_val and segundos_t is None:
                    st.error("⏱️ Tiempo inválido. Usa el formato HH:MM:SS (ejemplo: 01:42:15).")
                else:
                    tiempo_guardar = formatear_segundos(segundos_t) if segundos_t is not None else ""
                    conn_s = get_db_connection()
                    if conn_s:
                        cur_s = None
                        guardado = False
                        try:
                            cur_s = conn_s.cursor()
                            cur_s.execute("""
                                INSERT INTO partidos (usuario_id, codigo_partido, fecha, tiempo_ejecucion, tarifa, tipo_partido)
                                VALUES (%s, %s, %s, %s, %s, %s);
                            """, (user_id, codigo_p.strip(), fecha_p, tiempo_guardar, tarifa_calc, t_guardar))
                            conn_s.commit()
                            guardado = True
                        except Exception as e:
                            conn_s.rollback()
                            st.error(f"❌ No se pudo guardar el partido: {e}")
                        finally:
                            try:
                                if cur_s is not None: cur_s.close()
                            except Exception:
                                pass
                            cerrar_conexion(conn_s)

                        if guardado:
                            if t_guardar == "quincenal":
                                recalcular_tarifas_quincena_basket(user_id, fecha_p)
                            olvidar_recalculos()
                            st.cache_data.clear()
                            st.success("✅ Partido guardado exitosamente.")
                            st.rerun()

        conn_q = get_db_connection()
        if conn_q:
            if target_b_user_id == 0:
                df_basket = pd.read_sql_query("""
                    SELECT p.id, p.usuario_id, u.nombre as operador, p.codigo_partido, p.fecha, p.tiempo_ejecucion, p.tarifa, p.tipo_partido 
                    FROM partidos p
                    JOIN usuarios u ON p.usuario_id = u.id
                    WHERE p.fecha BETWEEN %s AND %s
                    ORDER BY p.fecha DESC, p.id DESC;
                """, conn_q, params=(f_ini, f_fin))
            else:
                df_basket = pd.read_sql_query("""
                    SELECT id, usuario_id, codigo_partido, fecha, tiempo_ejecucion, tarifa, tipo_partido 
                    FROM partidos 
                    WHERE usuario_id = %s AND fecha BETWEEN %s AND %s
                    ORDER BY fecha DESC, id DESC;
                """, conn_q, params=(target_b_user_id, f_ini, f_fin))
            cerrar_conexion(conn_q)
        else:
            df_basket = pd.DataFrame()

        st.markdown(f"### 📋 Registros de Básquetbol ({f_ini.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')})")
        if not df_basket.empty:
            total_ganancias = df_basket["tarifa"].astype(float).sum()
            col_k1, col_k2, col_k3 = st.columns(3)
            col_k1.metric("🏀 Total Partidos Quincena", len(df_basket), "📈 Actividad Alta")
            col_k2.metric("💵 Total Ganancias Quincena", f"${total_ganancias:.2f}", "🔺 En Alza")
            col_k3.metric("📅 Rango Evaluado", f"{f_ini.strftime('%d/%m')} - {f_fin.strftime('%d/%m/%Y')}")

            columnas_basket_visibles = [c for c in df_basket.columns if c != "usuario_id"]
            st.dataframe(df_basket[columnas_basket_visibles], use_container_width=True, hide_index=True)

            with st.expander("🛠️ Modificar, Corregir o Eliminar Cargas de Básquetbol"):
                tab_eb1, tab_eb2 = st.tabs(["✏️ Modificar / Corregir Partido", "🗑️ Eliminar Partido"])
                
                with tab_eb1:
                    list_ids_b = df_basket["id"].tolist()
                    id_edit_b = st.selectbox("Seleccione el ID del partido a corregir:", list_ids_b, key="sel_edit_b")
                    
                    row_b = df_basket[df_basket["id"] == id_edit_b].iloc[0]
                    with st.form("form_edit_b"):
                        fe_b = st.date_input("Fecha", value=pd.to_datetime(row_b["fecha"]).date())
                        cod_b = st.text_input("Código de Partido", value=str(row_b["codigo_partido"]))
                        t_b = st.text_input("Tiempo de Ejecución", value=str(row_b["tiempo_ejecucion"]))
                        propietario_b = int(row_b["usuario_id"])
                        if es_admin_estricto:
                            tar_b = st.number_input("Tarifa ($) — solo administrador", value=float(row_b["tarifa"]), step=0.50)
                        else:
                            tar_b = float(row_b["tarifa"])
                            st.caption(f"💵 Monto asignado: ${tar_b:.2f}. Solo el administrador puede modificarlo.")
                        
                        if st.form_submit_button("💾 Guardar Correcciones"):
                            t_b_limpio = (t_b or "").strip()
                            segs_edit = parsear_tiempo_a_segundos(t_b_limpio) if t_b_limpio else None
                            if t_b_limpio and segs_edit is None:
                                st.error("⏱️ Tiempo inválido. Usa el formato HH:MM:SS (ejemplo: 01:42:15).")
                            else:
                                tiempo_edit = formatear_segundos(segs_edit) if segs_edit is not None else ""
                                conn_eb = get_db_connection()
                                if conn_eb:
                                    cur_eb = None
                                    try:
                                        cur_eb = conn_eb.cursor()
                                        if es_admin_estricto:
                                            cur_eb.execute(
                                                "UPDATE partidos SET fecha=%s, codigo_partido=%s, tiempo_ejecucion=%s, tarifa=%s WHERE id=%s AND usuario_id=%s;",
                                                (fe_b, cod_b, tiempo_edit, tar_b, id_edit_b, propietario_b)
                                            )
                                        else:
                                            cur_eb.execute(
                                                "UPDATE partidos SET fecha=%s, codigo_partido=%s, tiempo_ejecucion=%s WHERE id=%s AND usuario_id=%s;",
                                                (fe_b, cod_b, tiempo_edit, id_edit_b, user_id)
                                            )
                                        if cur_eb.rowcount != 1:
                                            raise PermissionError("No tienes permiso para modificar este registro.")
                                        conn_eb.commit()
                                    except Exception as e:
                                        conn_eb.rollback()
                                        st.error(f"❌ No se pudo modificar el partido: {e}")
                                    finally:
                                        try:
                                            if cur_eb is not None: cur_eb.close()
                                        except Exception:
                                            pass
                                        cerrar_conexion(conn_eb)

                                    recalcular_tarifas_quincena_basket(propietario_b, fe_b)
                                    olvidar_recalculos()
                                    st.cache_data.clear()
                                    st.success("✅ Partido modificado y quincena recalculada con éxito.")
                                    st.rerun()

                with tab_eb2:
                    id_del_b = st.selectbox("Seleccione el ID del partido a eliminar:", df_basket["id"].tolist(), key="sel_del_b")
                    confirmo_del_b = st.checkbox("Confirmo que deseo eliminar este partido", key="conf_del_b")
                    if st.button("🚨 Confirmar y Eliminar Partido", use_container_width=True, disabled=not confirmo_del_b):
                        conn_db = get_db_connection()
                        if conn_db:
                            cur_db = None
                            fecha_borrada = hoy_local()
                            try:
                                cur_db = conn_db.cursor()
                                fila_borrar = df_basket[df_basket["id"] == id_del_b].iloc[0]
                                propietario_borrar = int(fila_borrar["usuario_id"])
                                cur_db.execute(
                                    "SELECT fecha FROM partidos WHERE id = %s AND usuario_id = %s;",
                                    (id_del_b, propietario_borrar)
                                )
                                r_f = cur_db.fetchone()
                                if not r_f:
                                    raise PermissionError("No tienes permiso para eliminar este registro.")
                                fecha_borrada = r_f[0]

                                cur_db.execute(
                                    "DELETE FROM partidos WHERE id = %s AND usuario_id = %s;",
                                    (id_del_b, propietario_borrar)
                                )
                                if cur_db.rowcount != 1:
                                    raise PermissionError("No tienes permiso para eliminar este registro.")
                                conn_db.commit()
                            except Exception as e:
                                conn_db.rollback()
                                st.error(f"❌ No se pudo eliminar el partido: {e}")
                            finally:
                                try:
                                    if cur_db is not None: cur_db.close()
                                except Exception:
                                    pass
                                cerrar_conexion(conn_db)

                            recalcular_tarifas_quincena_basket(propietario_borrar, fecha_borrada)
                            olvidar_recalculos()
                            st.cache_data.clear()
                            st.success("🗑️ Partido eliminado correctamente.")
                            st.rerun()

            csv_b = df_basket.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exportar Reporte Quincenal de Básquetbol (CSV)",
                data=csv_b,
                file_name=f"esam_basket_quincena_{f_ini}_al_{f_fin}.csv",
                mime="text/csv"
            )
        else:
            st.info("No hay registros de básquetbol para la quincena o periodo seleccionado.")

    # =========================================================
    # MÓDULO 2: BÉISBOL
    # =========================================================
    elif opcion_menu == "⚾ Módulo Béisbol":
        st.title("⚾ ESAM Analytics — Módulo Béisbol")

        target_beis_user_id = user_id
        if es_admin:
            df_usrs = obtener_todos_los_usuarios()
            if not df_usrs.empty:
                opciones_beis = {"🌐 CONSOLIDADO GLOBAL (TODOS LOS USUARIOS)": 0}
                for _, r_u in df_usrs.iterrows():
                    opciones_beis[f"👤 {r_u['nombre']} (@{r_u['username']})"] = r_u['id']
                
                u_beis_sel = st.sidebar.selectbox("👑 Ver Béisbol de:", list(opciones_beis.keys()))
                target_beis_user_id = opciones_beis[u_beis_sel]

        st.caption("Control de Picheos y Registros por Quincena")

        st.sidebar.markdown("---")
        st.sidebar.subheader("🔍 Filtro por Quincena y Periodo")

        f_ini, f_fin = selector_periodo("beisbol_periodo", "Seleccionar Periodo:")

        st.info(f"📅 **Periodo Evaluado Béisbol:** Del **{f_ini.strftime('%d/%m/%Y')}** al **{f_fin.strftime('%d/%m/%Y')}**")

        with st.expander("➕ Registrar Lote de Picheos", expanded=False):
            p1, p2, p3 = st.columns(3)
            with p1: f_pich = st.date_input("Fecha", value=hoy_local(), key="p_fich")
            with p2: id_ctrl = st.text_input("ID Control / Partido", placeholder="Ej: BC-2026")
            with p3: cant_pich = st.number_input("Cantidad de Picheos", min_value=1, step=1, value=100)

            if st.button("💾 Guardar Picheos", use_container_width=True):
                if not id_ctrl.strip():
                    st.warning("Ingrese el ID de control.")
                else:
                    conn_p = get_db_connection()
                    if conn_p:
                        cur_p = conn_p.cursor()
                        cur_p.execute("""
                            INSERT INTO picheos (usuario_id, fecha, id_control, cantidad)
                            VALUES (%s, %s, %s, %s);
                        """, (user_id, f_pich, id_ctrl.strip(), int(cant_pich)))
                        conn_p.commit()
                        cur_p.close()
                        conn_p.close()
                        st.cache_data.clear()
                        st.success("✅ Picheos guardados correctamente.")
                        st.rerun()

        conn_pb = get_db_connection()
        if conn_pb:
            if target_beis_user_id == 0:
                df_picheos = pd.read_sql_query("""
                    SELECT pi.id, pi.usuario_id, u.nombre as operador, pi.fecha, pi.id_control, pi.cantidad 
                    FROM picheos pi
                    JOIN usuarios u ON pi.usuario_id = u.id
                    WHERE pi.fecha BETWEEN %s AND %s
                    ORDER BY pi.fecha DESC, pi.id DESC;
                """, conn_pb, params=(f_ini, f_fin))
            else:
                df_picheos = pd.read_sql_query("""
                    SELECT id, usuario_id, fecha, id_control, cantidad 
                    FROM picheos 
                    WHERE usuario_id = %s AND fecha BETWEEN %s AND %s
                    ORDER BY fecha DESC, id DESC;
                """, conn_pb, params=(target_beis_user_id, f_ini, f_fin))
            cerrar_conexion(conn_pb)
        else:
            df_picheos = pd.DataFrame()

        st.markdown(f"### 📋 Listado de Picheos ({f_ini.strftime('%d/%m/%Y')} al {f_fin.strftime('%d/%m/%Y')})")
        if not df_picheos.empty:
            total_p = df_picheos["cantidad"].sum()
            precio_u = obtener_tasas_globales()["precio_beisbol"]
            total_dolares = total_p * precio_u

            cp1, cp2, cp3 = st.columns(3)
            cp1.metric("⚾ Total Picheos Quincena", f"{total_p:,}", "📈 Volumen Alto")
            cp2.metric("💵 USD Estimado", f"${total_dolares:,.2f}", f"@ ${precio_u}/u")
            cp3.metric("📅 Lotes Registrados", len(df_picheos), "🟢 Estable")

            columnas_picheos_visibles = [c for c in df_picheos.columns if c != "usuario_id"]
            st.dataframe(df_picheos[columnas_picheos_visibles], use_container_width=True, hide_index=True)

            with st.expander("🛠️ Modificar, Corregir o Eliminar Lotes de Picheos"):
                tab_ep1, tab_ep2 = st.tabs(["✏️ Modificar / Corregir Lote", "🗑️ Eliminar Lote"])
                
                with tab_ep1:
                    list_ids_p = df_picheos["id"].tolist()
                    id_edit_p = st.selectbox("Seleccione el ID del lote a corregir:", list_ids_p, key="sel_edit_p")
                    
                    row_p = df_picheos[df_picheos["id"] == id_edit_p].iloc[0]
                    propietario_p = int(row_p["usuario_id"])
                    with st.form("form_edit_p"):
                        fe_p = st.date_input("Fecha", value=pd.to_datetime(row_p["fecha"]).date())
                        id_c_p = st.text_input("ID Control / Partido", value=str(row_p["id_control"]))
                        cant_p = st.number_input("Cantidad de Picheos", value=int(row_p["cantidad"]), step=1, min_value=1)
                        
                        if st.form_submit_button("💾 Guardar Correcciones"):
                            conn_ep = get_db_connection()
                            if conn_ep:
                                cur_ep = conn_ep.cursor()
                                cur_ep.execute(
                                    "UPDATE picheos SET fecha=%s, id_control=%s, cantidad=%s WHERE id=%s AND usuario_id=%s;",
                                    (fe_p, id_c_p, int(cant_p), id_edit_p, propietario_p)
                                )
                                if cur_ep.rowcount != 1:
                                    raise PermissionError("No tienes permiso para modificar este lote.")
                                conn_ep.commit()
                                cur_ep.close()
                                conn_ep.close()
                                st.cache_data.clear()
                                st.success("✅ Lote de picheos modificado y corregido con éxito.")
                                st.rerun()

                with tab_ep2:
                    id_del_p = st.selectbox("Seleccione el ID del lote a eliminar:", df_picheos["id"].tolist(), key="sel_del_p")
                    confirmo_del_p = st.checkbox("Confirmo que deseo eliminar este lote", key="conf_del_p")
                    if st.button("🚨 Confirmar y Eliminar Lote", use_container_width=True, disabled=not confirmo_del_p):
                        conn_dp = get_db_connection()
                        if conn_dp:
                            cur_dp = None
                            try:
                                cur_dp = conn_dp.cursor()
                                fila_p_borrar = df_picheos[df_picheos["id"] == id_del_p].iloc[0]
                                propietario_p_borrar = int(fila_p_borrar["usuario_id"])
                                cur_dp.execute(
                                    "DELETE FROM picheos WHERE id = %s AND usuario_id = %s;",
                                    (id_del_p, propietario_p_borrar)
                                )
                                if cur_dp.rowcount != 1:
                                    raise PermissionError("No tienes permiso para eliminar este lote.")
                                conn_dp.commit()
                                st.cache_data.clear()
                                st.success("🗑️ Lote de picheos eliminado correctamente.")
                                st.rerun()
                            except Exception as e:
                                conn_dp.rollback()
                                st.error(f"❌ No se pudo eliminar el lote: {e}")
                            finally:
                                try:
                                    if cur_dp is not None: cur_dp.close()
                                except Exception:
                                    pass
                                cerrar_conexion(conn_dp)

            csv_b = df_picheos.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exportar Reporte Quincenal de Béisbol (CSV)",
                data=csv_b,
                file_name=f"esam_beisbol_quincena_{f_ini}_al_{f_fin}.csv",
                mime="text/csv"
            )
        else:
            st.info("No hay registros de picheos para la quincena o periodo seleccionado.")

    # =========================================================
    # MÓDULO: ADMINISTRACIÓN DE PRECIOS POR DEPORTE (EXCLUSIVO ADMIN)
    # =========================================================
    elif opcion_menu == "⚙️ Administración de Precios por Deporte" and es_admin_estricto:
        st.title("⚙️ PANEL DE CONTROL Y CONFIGURACIÓN DE TARIFAS")
        st.caption("Ajusta en tiempo real los valores en USD asignados a cada disciplina deportiva")

        tasas_actuales = obtener_tasas_globales()

        tab_p_basket, tab_p_beis = st.tabs(["🏀 Tarifas de Básquetbol", "⚾ Precios de Béisbol"])

        with tab_p_basket:
            st.subheader("🏀 Tarifas y Tramos de Básquetbol")
            with st.form("form_admin_basket_prices"):
                st.markdown("##### 📈 Tramos Quincenales (USD por partido):")
                cb1, cb2, cb3, cb4, cb5 = st.columns(5)
                with cb1: nt1 = st.number_input("Tramo 1 (1 - 11 partidos)", value=tasas_actuales["tramo_1"], step=0.25)
                with cb2: nt2 = st.number_input("Tramo 2 (12 - 14 partidos)", value=tasas_actuales["tramo_2"], step=0.25)
                with cb3: nt3 = st.number_input("Tramo 3 (15 - 26 partidos)", value=tasas_actuales["tramo_3"], step=0.25)
                with cb4: nt4 = st.number_input("Tramo 4 (27 - 29 partidos)", value=tasas_actuales["tramo_4"], step=0.25)
                with cb5: nt5 = st.number_input("Tramo 5 (30+ partidos)", value=tasas_actuales["tramo_5"], step=0.25)

                st.markdown("---")
                st.markdown("##### ⚡ Modalidad Especial En Vivo:")
                cbe1, cbe2 = st.columns(2)
                with cbe1: n_norm = st.number_input("Partido En Vivo Normal ($)", value=tasas_actuales["en_vivo_normal"], step=0.50)
                with cbe2: n_nba = st.number_input("Partido En Vivo NBA ($)", value=tasas_actuales["en_vivo_nba"], step=0.50)

                sub_b_prices = st.form_submit_button("💾 Actualizar Tarifas de Básquetbol", use_container_width=True)
                if sub_b_prices:
                    actualizar_tasa_global("tasa_tramo_1", nt1)
                    actualizar_tasa_global("tasa_tramo_2", nt2)
                    actualizar_tasa_global("tasa_tramo_3", nt3)
                    actualizar_tasa_global("tasa_tramo_4", nt4)
                    actualizar_tasa_global("tasa_tramo_5", nt5)
                    actualizar_tasa_global("tasa_en_vivo_normal", n_norm)
                    actualizar_tasa_global("tasa_en_vivo_nba", n_nba)
                    olvidar_recalculos()
                    st.success("✅ Tarifas de Básquetbol actualizadas con éxito.")
                    st.rerun()

        with tab_p_beis:
            st.subheader("⚾ Tarifa Unitaria de Béisbol")
            with st.form("form_admin_beis_prices"):
                n_precio_beis = st.number_input("Precio por Picheo Registrado (USD)", value=tasas_actuales["precio_beisbol"], format="%.4f", step=0.001)
                sub_beis_price = st.form_submit_button("💾 Actualizar Precio de Béisbol", use_container_width=True)
                if sub_beis_price:
                    actualizar_tasa_global("precio_beisbol", n_precio_beis)
                    st.success("✅ Precio por picheo de Béisbol actualizado con éxito.")
                    st.rerun()

    # =========================================================
    # MÓDULO: SEGURIDAD Y CREDENCIALES (INTELIGENTE)
    # =========================================================
    elif opcion_menu == "🔐 Seguridad y Contraseñas":
        st.title("🔐 Gestión de Seguridad y Contraseñas")

        if es_admin:
            st.caption("👑 MODO ADMINISTRADOR: Puedes cambiar la contraseña de cualquier operador sin saber la clave anterior.")
            df_usrs_pass = obtener_todos_los_usuarios()
            
            if not df_usrs_pass.empty:
                opciones_u_pass = {}
                for _, r_u in df_usrs_pass.iterrows():
                    opciones_u_pass[f"👤 {r_u['nombre']} (@{r_u['username']})"] = r_u['id']
                
                u_pass_sel = st.selectbox("Selecciona el usuario al que deseas cambiarle la contraseña:", list(opciones_u_pass.keys()))
                user_id_target = opciones_u_pass[u_pass_sel]

                with st.form("form_cambiar_pass_admin"):
                    pass_nueva = st.text_input("Escribe la Nueva Contraseña para este Usuario", type="password")
                    pass_conf = st.text_input("Confirmar Nueva Contraseña", type="password")

                    submit_pass = st.form_submit_button("🔒 Forzar Cambio de Contraseña", use_container_width=True)

                    if submit_pass:
                        if not (pass_nueva and pass_conf):
                            st.warning("Por favor complete todos los campos.")
                        elif pass_nueva != pass_conf:
                            st.error("Las nuevas contraseñas no coinciden.")
                        elif len(pass_nueva) < 6:
                            st.error("La nueva contraseña debe tener al menos 6 caracteres.")
                        else:
                            exito_c, msg_c = cambiar_password_usuario(user_id_target, pass_nueva)
                            if exito_c:
                                st.success(f"✅ Contraseña reescrita con éxito para {u_pass_sel}.")
                            else:
                                st.error(msg_c)
        else:
            st.caption(f"Actualiza la contraseña de tu cuenta individual — {user_name}")

            with st.form("form_cambiar_pass_user"):
                pass_vieja = st.text_input("Contraseña Actual", type="password")
                pass_nueva = st.text_input("Nueva Contraseña", type="password")
                pass_conf = st.text_input("Confirmar Nueva Contraseña", type="password")

                submit_pass = st.form_submit_button("🔒 Actualizar Mi Contraseña", use_container_width=True)

                if submit_pass:
                    if not (pass_vieja and pass_nueva and pass_conf):
                        st.warning("Por favor complete todos los campos.")
                    elif pass_nueva != pass_conf:
                        st.error("Las nuevas contraseñas no coinciden.")
                    elif len(pass_nueva) < 6:
                        st.error("La nueva contraseña debe tener al menos 6 caracteres.")
                    else:
                        user_verif = autenticar_usuario(st.session_state.user_info["username"], pass_vieja)
                        if not user_verif:
                            st.error("❌ La contraseña actual es incorrecta.")
                        else:
                            exito_c, msg_c = cambiar_password_usuario(user_id, pass_nueva)
                            if exito_c:
                                st.success(msg_c)
                            else:
                                st.error(msg_c)
