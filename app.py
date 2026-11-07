from contextlib import closing
from datetime import date

import pandas as pd
import psycopg2
import streamlit as st

st.set_page_config(
    page_title="Control de Asistencia Dominical", page_icon="⛪", layout="wide"
)

# Configuración de URL del Google Sheet
SHEET_CSV_URL = st.secrets.get(
    "SHEET_CSV_URL",
    "https://docs.google.com/spreadsheets/d/1hiCHC8j2PmMcbrnecPc64aDdbXEbAcXmgEfz6wxy1DY/export?format=csv",
)


# Conexión helper a PostgreSQL (Neon)
def get_db_connection():
    return psycopg2.connect(st.secrets["neon_db"]["url"])


# Inicializar tabla si no existe
@st.cache_resource
def inicializar_tabla():
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS asistencia_domingos (
                id SERIAL PRIMARY KEY,
                documento_identidad VARCHAR(50) NOT NULL,
                fecha DATE NOT NULL,
                estado VARCHAR(20) NOT NULL,
                UNIQUE(documento_identidad, fecha)
            );
        """)
        conn.commit()


try:
    inicializar_tabla()
except Exception as e:
    st.error(f"Error al inicializar la base de datos: {e}")
    st.stop()


# Carga, filtrado estricto por congregación y estandarización del Google Sheet
@st.cache_data(ttl=60)
def cargar_miembros(url):
    doc_col = "Número de Documento. Sin espacios, puntos ni guiones."
    try:
        df = pd.read_csv(
            url,
            usecols=[1, 2, 3, 4],
            dtype={doc_col: "string"},
        )

        # 1. Filtrar exclusivamente la congregación "Arauca Central"
        if "Congregación" in df.columns:
            df = df[
                df["Congregación"].astype(str).str.strip() == "Arauca Central"
            ]

        # 2. Renombrar la columna del documento a un identificador interno ("ID")
        if doc_col in df.columns:
            df.rename(columns={doc_col: "ID"}, inplace=True)
            df["ID"] = df["ID"].str.strip()

        return df[["Congregación", "Apellidos", "Nombres", "ID"]]
    except Exception as e:
        st.error(f"Error al leer el Google Sheet: {e}")
        return pd.DataFrame()


# Consultar quiénes YA asistieron en la fecha seleccionada
def obtener_asistentes_del_dia(fecha_asistencia):
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
            SELECT documento_identidad
            FROM asistencia_domingos
            WHERE fecha = %s AND estado = 'Presente';
        """,
                (fecha_asistencia,),
            )
            filas = cur.fetchall()
    return {str(fila[0]).strip() for fila in filas}


# Guardar / Actualizar Asistencia (Anti-Duplicados)
def guardar_asistencia_en_db(fecha_asistencia, df_asistencia):
    try:
        with closing(get_db_connection()) as conn:
            with conn:
                with conn.cursor() as cur:
                    registros_guardados = 0
                    for _, row in df_asistencia.iterrows():
                        doc_id = str(row["ID"]).strip()
                        asistio = row["Asistió"]
                        estado = "Presente" if asistio else "Ausente"

                        # UPSERT actualiza el estado sin crear duplicados.
                        cur.execute(
                            """
                INSERT INTO asistencia_domingos (documento_identidad, fecha, estado)
                VALUES (%s, %s, %s)
                ON CONFLICT (documento_identidad, fecha)
                DO UPDATE SET estado = EXCLUDED.estado;
            """,
                            (doc_id, fecha_asistencia, estado),
                        )
                        if asistio:
                            registros_guardados += 1
        return True, registros_guardados
    except Exception as e:
        return False, str(e)


# --- INTERFAZ DE USUARIO ---
st.title("⛪ Control de Asistencia Dominical - Arauca Central")
st.markdown(
    "Selecciona la fecha del culto, marca la asistencia y guarda los cambios."
)

# Barra lateral
with st.sidebar:
    st.header("⚙️ Configuración")
    fecha_seleccionada = st.date_input(
        "Fecha del Culto", value=date.today(), key="fecha_culto"
    )

    st.divider()
    st.markdown("### 📝 Registrar Nuevo Miembro")
    st.markdown(
        "Si la persona no aparece en la lista, regístrala en el formulario:"
    )
    st.link_button(
        "➕ Abrir Google Form",
        "https://docs.google.com/forms/d/e/1FAIpQLSebAYDLGRjT9RZpqE6UaNtRyOUEShIpnTf2QKvkzk81Kx1lyw/viewform?pli=1&pli=1",
        use_container_width=True,
    )
    st.caption(
        "💡 Guarda tu asistencia actual antes de abrir el formulario externo."
    )

# Cargar datos filtrados
df_miembros = cargar_miembros(SHEET_CSV_URL)

if df_miembros.empty:
    st.warning(
        "No se encontraron registros para 'Arauca Central' o el enlace de Google"
        " Sheets no es accesible."
    )
else:
    required_columns = {"Congregación", "ID", "Nombres", "Apellidos"}
    missing_columns = required_columns.difference(df_miembros.columns)
    if missing_columns:
        st.error(
            "Faltan columnas requeridas en el Google Sheet: "
            + ", ".join(sorted(missing_columns))
        )
        st.stop()

    df_miembros = df_miembros[
        df_miembros["ID"].notna() & df_miembros["ID"].ne("")
    ].copy()

    if df_miembros.empty:
        st.warning("No hay miembros con documento de identidad válido.")
    else:
        try:
            asistentes_previos = obtener_asistentes_del_dia(
                fecha_seleccionada
            )
        except Exception as e:
            st.error(f"Error al consultar asistencias previas: {e}")
            st.stop()

        # Marcar con True si ya asistió hoy previamente en Neon.
        df_miembros["Asistió"] = df_miembros["ID"].isin(asistentes_previos)

        df_miembros = df_miembros.sort_values(
            ["Nombres", "Apellidos"],
            key=lambda columna: (
                columna.fillna("").astype(str).str.strip().str.casefold()
            ),
            kind="stable",
        )
        df_miembros = df_miembros[
            ["Asistió", "ID", "Nombres", "Apellidos", "Congregación"]
        ]

        total_presentes_hoy = int(df_miembros["Asistió"].sum())
        st.info(
            f"📅 **Asistentes confirmados hoy ({fecha_seleccionada}):**"
            f" **{total_presentes_hoy}** de {len(df_miembros)} miembros de Arauca"
            " Central."
        )

        df_editado = st.data_editor(
            df_miembros,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Asistió": st.column_config.CheckboxColumn(
                    "¿Asistió hoy?", default=False
                ),
                "Congregación": st.column_config.TextColumn(
                    "Congregación", disabled=True
                ),
                "ID": st.column_config.TextColumn(
                    "Cédula / Número de Documento",
                    disabled=True,
                ),
                "Nombres": st.column_config.TextColumn(
                    "Nombres", disabled=True
                ),
                "Apellidos": st.column_config.TextColumn(
                    "Apellidos", disabled=True
                ),
            },
            key=f"editor_{fecha_seleccionada}",
        )

        col1, _ = st.columns([1, 4])
        with col1:
            btn_guardar = st.button(
                "💾 Guardar Asistencia", type="primary", use_container_width=True
            )

        if btn_guardar:
            with st.spinner("Actualizando registros en Neon..."):
                exito, resultado = guardar_asistencia_en_db(
                    fecha_seleccionada, df_editado
                )
                if exito:
                    st.success(
                        "¡Asistencia guardada con éxito! No se generaron duplicados."
                    )
                    st.rerun()
                else:
                    st.error(f"Error al guardar: {resultado}")