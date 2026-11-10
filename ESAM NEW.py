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
ZONA_HORARIA_UTC_OFFSET = -4  # Venezuela / Bolivia (UTC-4)

def ahora_local():
    """Fecha y hora local real del operador (UTC + desfase)."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=ZONA_HORARIA_UTC_OFFSET)

def hoy_local():
    """Fecha de HOY según la hora local del operador."""
    return ahora_local().date()

# =========================================================
# 0.1 UTILIDADES DE TIEMPO Y OFIMÁTICA (HH:MM:SS)
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
# 1. CONFIGURACIÓN GENERAL Y ESTILOS VISUALES (NEGRO Y ROJO TÁCTICO)
# =========================================================
st.set_page_config(
    page_title="ESAM Analytics 360°",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Inter+Tight:wght@600;700;800&display=swap');

:root {
    --bg: #050505;
    --surface: #121215;
    --surface-hover: #1A1A21;
    --line: #272733;
    --line-focus: #E63946;
    --ink: #F8F9FA;
    --ink-2: #9CA3AF;
    --primary: #E63946;
    --primary-dark: #C5222E;
    --primary-tint: rgba(230, 57, 70, 0.12);
    --ok: #2DC653;
    --ball-accent: #FFB703;
    --dollar-accent: #2A9D8F;
    --radius: 10px;
    --radius-lg: 16px;
    --shadow: 0 10px 30px rgba(0, 0, 0, 0.8);
}

*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid='stAppViewContainer'], [data-testid='stApp'] {
    background: var(--bg) !important;
    color: var(--ink) !important;
    font-family: 'Inter', sans-serif !important;
}

[data-testid='stHeader'] { background: transparent !important; }
#MainMenu, footer, [data-testid='stDecoration'] { display: none !important; }

.block-container {
    padding-top: 2rem !important;
    padding-bottom: 4rem !important;
    max-width: 1300px !important;
}

h1, h2, h3 {
    font-family: 'Inter Tight', sans-serif !important;
    color: var(--ink) !important;
}

h1 {
    font-size: 1.8rem !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, #FF1E38 0%, #E63946 50%, #8D0801 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--line);
    margin-bottom: 1.5rem !important;
}

[data-testid='stMetric'], [data-testid='stForm'], [data-testid='stExpander'], [data-testid='stDataFrame'] {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--shadow) !important;
    padding: 1.2rem !important;
}

[data-testid='stMetricValue'] {
    color: var(--primary) !important;
    font-family: 'Inter Tight', sans-serif !important;
    font-weight: 700 !important;
}

[data-testid='stSidebar'] {
    background: #08080A !important;
    border-right: 1px solid var(--line) !important;
}

.stButton > button, [data-testid='stFormSubmitButton'] > button {
    background: linear-gradient(135deg, #E63946 0%, #C5222E !important);
    color: #FFFFFF !important;
    font-weight: 700 !important;
    border-radius: var(--radius) !important;
    border: none !important;
    padding: 0.6rem 1.2rem !important;
    box-shadow: 0 4px 14px rgba(230, 57, 70, 0.4) !important;
    transition: transform 0.2s ease, box-shadow 0.2s ease !important;
}

.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(230, 57, 70, 0.6) !important;
}

[data-testid='stTextInputRootElement'], [data-testid='stNumberInputContainer'] {
    background: var(--surface) !important;
    border: 1px solid var(--line) !important;
    border-radius: var(--radius) !important;
}

.stTextInput input, .stNumberInput input {
    color: var(--ink) !important;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. SEGURIDAD Y ENCRIPTACIÓN (PBKDF2-SHA256)
# =========================================================
PBKDF2_ITERACIONES = 240_000

def hash_password(password: str) -> str:
    sal = os.urandom(16)
    digesto = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, PBKDF2_ITERACIONES)
    return f"pbkdf2_sha256${PBKDF2_ITERACIONES}${sal.hex()}${digesto.hex()}"

def verificar_password(password: str, hash_guardado) -> bool:
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
    return hmac.compare_digest(hashlib.sha256(password.encode("utf-8")).hexdigest(), guardado)

def _secreto(clave, defecto=None):
    try:
        if clave in st.secrets:
            return st.secrets[clave]
    except Exception:
        pass
    return defecto

ADMIN_PASSWORD_INICIAL = _secreto("admin_password", "admin123")
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
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass

# =========================================================
# 4. INICIALIZACIÓN COMPLETA DE TABLAS
# =========================================================
def init_db():
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
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS registros_analiticos (
                id SERIAL PRIMARY KEY,
                fecha DATE NOT NULL,
                tipo_activo VARCHAR(50) NOT NULL,
                categoria VARCHAR(100) NOT NULL,
                descripcion TEXT,
                valor NUMERIC(14, 2) DEFAULT 0.00,
                operador VARCHAR(50),
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS configuracion_global (
                clave VARCHAR(50) PRIMARY KEY,
                valor NUMERIC(10, 4) NOT NULL
            );
        """)
        
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
            if cur is not None: cur.close()
        except Exception:
            pass
        cerrar_conexion(conn)

if not st.session_state.get("_db_iniciada"):
    st.session_state["_db_iniciada"] = init_db()

# =========================================================
# 5. GESTIÓN DE SESIÓN Y LOGIN
# =========================================================
if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False
    st.session_state["usuario"] = None
    st.session_state["rol"] = None
    st.session_state["nombre_usuario"] = None

def autenticar_usuario(username, password):
    conn = get_db_connection()
    if not conn:
        return False
    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, username, nombre, password_hash, password, rol FROM usuarios WHERE username = %s;", (username,))
        user = cur.fetchone()
        if user:
            hash_g = user["password_hash"] or user["password"]
            if verificar_password(password, hash_g):
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = user["username"]
                st.session_state["rol"] = user["rol"]
                st.session_state["nombre_usuario"] = user["nombre"]
                return True
        return False
    except Exception as e:
        st.error(f"Error en autenticación: {e}")
        return False
    finally:
        try:
            if cur is not None: cur.close()
        except Exception:
            pass
        cerrar_conexion(conn)

if not st.session_state["autenticado"]:
    st.markdown("<h1 style='text-align: center;'>ESAM Analytics 360°</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Centro Táctico de Análisis, Balones y Finanzas</p>", unsafe_allow_html=True)
    
    tab_login, tab_info = st.tabs(["🔐 Iniciar Sesión", "ℹ️ Información"])
    with tab_login:
        with st.form("form_login"):
            st.markdown("### Credenciales de Acceso")
            u_input = st.text_input("Usuario")
            p_input = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Entrar al Sistema")
            if submitted:
                if autenticar_usuario(u_input, p_input):
                    st.success("✅ Acceso concedido. Cargando centro táctico...")
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos.")
    with tab_info:
        st.info("💡 Sistema protegido con cifrado PBKDF2-SHA256, modo táctico negro/rojo y UTC-4.")
    st.stop()

# =========================================================
# 6. FUNCIONES DE OFIMÁTICA Y DATOS
# =========================================================
def guardar_registro_db(fecha, tipo_activo, categoria, descripcion, valor, operador):
    conn = get_db_connection()
    if not conn:
        return False
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO registros_analiticos (fecha, tipo_activo, categoria, descripcion, valor, operador)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (fecha, tipo_activo, categoria, descripcion, valor, operador))
        return True
    except Exception as e:
        st.error(f"❌ Error al guardar: {e}")
        return False
    finally:
        try:
            if cur is not None: cur.close()
        except Exception:
            pass
        cerrar_conexion(conn)

def obtener_registros_db():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = "SELECT id, fecha, tipo_activo, categoria, descripcion, valor, operador, creado_en FROM registros_analiticos ORDER BY fecha DESC, id DESC;"
        df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"❌ Error al consultar registros: {e}")
        return pd.DataFrame()
    finally:
        cerrar_conexion(conn)

# =========================================================
# 7. INTERFAZ PRINCIPAL DEL CENTRO TÁCTICO
# =========================================================
st.title("ESAM Analytics 360° — Centro Táctico Integral")

with st.sidebar:
    st.markdown(f"👤 **Operador:** {st.session_state['nombre_usuario']}")
    st.markdown(f"🛡️ **Rol:** {st.session_state['rol'].upper()}")
    st.markdown("---")
    st.markdown("### 🔴 Menú Táctico")
    opcion = st.radio("Módulos:", ["Dashboard Ejecutivo", "Gestión Ofimática y Datos", "Reportes y Exportación", "Configuración y Seguridad"])
    
    st.markdown("---")
    if st.button("Cerrar Sesión"):
        st.session_state["autenticado"] = False
        st.rerun()

df_regs = obtener_registros_db()

if opcion == "Dashboard Ejecutivo":
    st.subheader("📊 Métricas de Rendimiento en Tiempo Real")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        total_balones = len(df_regs[df_regs['tipo_activo'].str.contains("Balón|Deportivo", case=False, na=False)]) if not df_regs.empty else 0
        st.metric(label="🏀 Analíticas de Balones / Partidos", value=str(total_balones), delta="Activo en pista")
    with col2:
        total_dolares = df_regs[df_regs['tipo_activo'].str.contains("Dólar|Finanzas", case=False, na=False)]['valor'].sum() if not df_regs.empty else 0.0
        st.metric(label="💵 Control de Dólares / Finanzas", value=f"${total_dolares:,.2f}", delta="Suma de caja")
    with col3:
        st.metric(label="Sincronización Horaria", value="UTC-4 (Local)", delta="Estable")
        
    st.info("💡 Centro Táctico operando con paleta Negro/Rojo de alto rendimiento y segmentación por tipo de activo.")
    
    if not df_regs.empty:
        st.subheader("📋 Historial Reciente de Operaciones")
        st.dataframe(df_regs, use_container_width=True)
    else:
        st.warning("⚠️ No hay registros almacenados todavía. Utiliza el módulo de Ofimática y Datos para agregar información.")

elif opcion == "Gestión Ofimática y Datos":
    st.subheader("📁 Módulo de Ofimática y Carga de Registros")
    st.write("Administra, procesa y registra información analítica de balones y finanzas de forma segura.")
    
    with st.form("form_ofimatica"):
        st.markdown("#### Nuevo Registro en el Sistema")
        f_fecha = st.date_input("Fecha del Registro", value=hoy_local())
        f_tipo = st.selectbox("Tipo de Activo", ["🏀 Rendimiento de Balones / Scouting", "💵 Transacción en Dólares / Finanzas", "📊 Operaciones Generales"])
        f_cat = st.text_input("Categoría Específica", placeholder="Ej. Temporada Regular, Caja Chica, etc.")
        f_val = st.number_input("Valor Numérico / Métrica / Monto ($)", value=0.0, format="%.2f")
        f_desc = st.text_area("Detalles o notas de ofimática")
        f_operador = st.text_input("Operador a Cargo", value=st.session_state["nombre_usuario"])
        
        submitted = st.form_submit_button("Guardar Registro Táctico")
        if submitted:
            if not f_cat.strip():
                st.error("❌ Por favor indica una categoría válida.")
            else:
                exito = guardar_registro_db(f_fecha, f_tipo, f_cat, f_desc, f_val, f_operador)
                if exito:
                    st.success("✅ ¡Registro almacenado y sincronizado correctamente en la base de datos!")
                    st.rerun()

elif opcion == "Reportes y Exportación":
    st.subheader("📥 Reportes y Exportación de Datos")
    st.write("Genera y descarga reportes detallados en formato CSV para respaldos de ofimática.")
    
    if not df_regs.empty:
        csv_data = df_regs.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Descargar Reporte Completo en CSV",
            data=csv_data,
            file_name=f"esam_analytics_reporte_{hoy_local()}.csv",
            mime="text/csv"
        )
        st.dataframe(df_regs, use_container_width=True)
    else:
        st.info("ℹ️ No hay datos disponibles para exportar en este momento.")

else:
    st.subheader("⚙️ Configuración y Seguridad")
    st.write("Parámetros de conexión, control de accesos y mantenimiento del sistema.")
    st.markdown("- **Base de datos:** Conectado a Neon PostgreSQL.")
    st.markdown("- **Seguridad de Claves:** Cifrado PBKDF2-SHA256 con 240,000 iteraciones.")
    st.markdown("- **Zona Horaria:** Configurado para UTC-4 (Venezuela / Operador).")
