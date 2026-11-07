import hmac
from base64 import b64encode
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st

from attendance_logic import (
    aplicar_ediciones_editor,
    contar_cambios,
    filtrar_cambios_asistencia,
    filtrar_miembros,
    obtener_documentos_duplicados,
)

st.set_page_config(
    page_title="Control de Asistencia Dominical", page_icon="⛪", layout="wide"
)


def autenticar_usuario():
    try:
        password_configurada = st.secrets["auth"]["password"]
    except (KeyError, TypeError):
        st.error(
            "Falta configurar [auth].password en .streamlit/secrets.toml. "
            "Consulta README.md para ver los pasos."
        )
        st.stop()

    if not isinstance(password_configurada, str) or len(password_configurada) < 16:
        st.error("La contraseña configurada debe tener al menos 16 caracteres.")
        st.stop()

    if st.session_state.get("autenticado", False):
        return

    st.title("Acceso al control de asistencia")
    with st.form("formulario_inicio_sesion"):
        password_ingresada = st.text_input(
            "Contraseña", type="password", autocomplete="current-password"
        )
        enviar = st.form_submit_button("Ingresar", type="primary")

    if enviar:
        if hmac.compare_digest(password_ingresada, password_configurada):
            st.session_state["autenticado"] = True
            st.rerun()
        st.error("La contraseña no es correcta.")
    st.stop()


autenticar_usuario()

mensaje_guardado = st.session_state.pop("mensaje_guardado", None)
if mensaje_guardado:
    st.success(mensaje_guardado)

LOGO_PATH = Path(__file__).with_name("logo.png")
try:
    LOGO_BASE64 = b64encode(LOGO_PATH.read_bytes()).decode("ascii")
except OSError as e:
    st.error(f"No se pudo cargar el logo de la aplicación: {e}")
    st.stop()

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1380px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    .attendance-hero {
        display: flex;
        align-items: center;
        gap: 1.6rem;
        margin: 0 0 1.5rem;
        padding: 1.6rem 2rem;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 22px;
        background: linear-gradient(120deg, #102c3c 0%, #1c5260 100%);
        box-shadow: 0 14px 36px rgba(16, 44, 60, 0.16);
        color: #fff;
    }

    .attendance-hero img {
        display: block;
        width: 92px;
        height: auto;
        flex: 0 0 auto;
        filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.18));
    }

    .attendance-kicker {
        margin: 0 0 0.35rem;
        color: #e8c879;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
    }

    .attendance-hero h1 {
        margin: 0;
        color: #fff;
        font-size: clamp(1.7rem, 3vw, 2.45rem);
        font-weight: 700;
        line-height: 1.15;
    }

    .attendance-hero p {
        margin: 0.55rem 0 0;
        color: #d7e5e8;
        font-size: 1rem;
    }

    @media (max-width: 640px) {
        .attendance-hero {
            gap: 1rem;
            padding: 1.2rem;
            border-radius: 16px;
        }

        .attendance-hero img {
            width: 68px;
        }

    }
    </style>
    """,
    unsafe_allow_html=True,
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
def obtener_estados_del_dia(fecha_asistencia):
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
            SELECT documento_identidad, estado
            FROM asistencia_domingos
            WHERE fecha = %s;
        """,
                (fecha_asistencia,),
            )
            filas = cur.fetchall()
    return {
        str(documento).strip(): estado == "Presente"
        for documento, estado in filas
    }


def obtener_resumen_historial(fecha_inicio, fecha_fin):
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fecha,
                       COUNT(*) FILTER (WHERE estado = 'Presente') AS presentes,
                       COUNT(*) FILTER (WHERE estado = 'Ausente') AS ausentes
                FROM asistencia_domingos
                WHERE fecha BETWEEN %s AND %s
                GROUP BY fecha
                ORDER BY fecha DESC;
                """,
                (fecha_inicio, fecha_fin),
            )
            filas = cur.fetchall()
    return pd.DataFrame(filas, columns=["Fecha", "Presentes", "Ausentes"])


def obtener_detalle_historial(fecha_asistencia):
    with closing(get_db_connection()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT documento_identidad, estado
                FROM asistencia_domingos
                WHERE fecha = %s
                ORDER BY documento_identidad;
                """,
                (fecha_asistencia,),
            )
            filas = cur.fetchall()
    return pd.DataFrame(filas, columns=["ID", "Estado"])


# Guardar / Actualizar Asistencia (Anti-Duplicados)
def guardar_asistencia_en_db(
    fecha_asistencia, df_asistencia, estados_originales
):
    try:
        cambios = filtrar_cambios_asistencia(
            df_asistencia, estados_originales
        )
        with closing(get_db_connection()) as conn:
            with conn:
                with conn.cursor() as cur:
                    for _, row in cambios.iterrows():
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
        return True, len(cambios)
    except Exception as e:
        return False, str(e)


# --- INTERFAZ DE USUARIO ---
st.markdown(
    f"""
    <header class="attendance-hero">
        <img src="data:image/png;base64,{LOGO_BASE64}"
             alt="Logo de la Congregación Cristiana Alianza de Colombia">
        <div>
            <div class="attendance-kicker">Registro dominical</div>
            <h1>Control de asistencia</h1>
            <p>Iglesia Evangélica Alianza Central Arauca</p>
        </div>
    </header>
    """,
    unsafe_allow_html=True,
)

# Barra lateral
with st.sidebar:
    st.header("Configuración")
    if st.button("Cerrar sesión", width="stretch"):
        st.session_state["autenticado"] = False
        claves_privadas = (
            "borrador_",
            "editor_",
            "ids_editor_",
            "firma_filtro_",
            "confirmar_",
            "generacion_guardado_",
            "generacion_historial_",
            "mensaje_guardado",
        )
        for clave in list(st.session_state.keys()):
            if clave.startswith(claves_privadas):
                st.session_state.pop(clave, None)
        st.rerun()

    fecha_seleccionada = st.date_input(
        "Fecha del Culto", value=date.today(), key="fecha_culto"
    )

    st.subheader("Registrar nuevo miembro")
    st.markdown(
        "Si la persona no aparece en la lista, regístrala en el formulario:"
    )
    st.link_button(
        "Abrir Google Form",
        "https://docs.google.com/forms/d/e/1FAIpQLSebAYDLGRjT9RZpqE6UaNtRyOUEShIpnTf2QKvkzk81Kx1lyw/viewform?pli=1&pli=1",
        width="stretch",
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
        documentos_duplicados = obtener_documentos_duplicados(df_miembros)
        hay_documentos_duplicados = len(documentos_duplicados) > 0
        if hay_documentos_duplicados:
            st.error(
                f"Hay {len(documentos_duplicados)} documentos repetidos en el "
                "Google Sheet. Corrígelos antes de guardar asistencia."
            )
            st.dataframe(
                df_miembros[df_miembros["ID"].isin(documentos_duplicados)][
                    ["ID", "Nombres", "Apellidos"]
                ],
                width="stretch",
                hide_index=True,
            )

        try:
            estados_originales = obtener_estados_del_dia(
                fecha_seleccionada
            )
        except Exception as e:
            st.error(f"Error al consultar asistencias previas: {e}")
            st.stop()

        df_miembros["Asistió"] = (
            df_miembros["ID"]
            .map(estados_originales)
            .astype("boolean")
            .fillna(False)
            .astype(bool)
        )

        df_miembros = df_miembros.sort_values(
            ["Nombres", "Apellidos"],
            key=lambda columna: (
                columna.fillna("").astype(str).str.strip().str.casefold()
            ),
            kind="stable",
        ).reset_index(drop=True)
        df_miembros = df_miembros[
            ["Asistió", "ID", "Nombres", "Apellidos", "Congregación"]
        ]

        documentos = df_miembros["ID"].tolist()
        borrador_key = f"borrador_{fecha_seleccionada}"
        if borrador_key not in st.session_state:
            st.session_state[borrador_key] = {
                documento: bool(estados_originales.get(documento, False))
                for documento in documentos
            }
        borrador = st.session_state[borrador_key]
        for documento in documentos:
            borrador.setdefault(
                documento, bool(estados_originales.get(documento, False))
            )

        editor_key = f"editor_{fecha_seleccionada}"
        ids_visibles_key = f"ids_editor_{fecha_seleccionada}"
        firma_filtro_key = f"firma_filtro_{fecha_seleccionada}"
        ids_visibles_anteriores = st.session_state.get(ids_visibles_key, [])
        aplicar_ediciones_editor(
            st.session_state.get(editor_key, {}),
            ids_visibles_anteriores,
            borrador,
        )

        col_busqueda, col_filtro = st.columns([2, 1])
        with col_busqueda:
            consulta = st.text_input(
                "Buscar por nombre, apellido o cédula",
                key=f"busqueda_{fecha_seleccionada}",
                placeholder="Escribe para filtrar la lista",
            )
        with col_filtro:
            filtro_asistencia = st.segmented_control(
                "Mostrar",
                options=["Todos", "Presentes", "Pendientes"],
                default="Todos",
                key=f"filtro_asistencia_{fecha_seleccionada}",
                width="stretch",
            )
        filtro_asistencia = filtro_asistencia or "Todos"
        firma_filtro = (consulta.strip().casefold(), filtro_asistencia)
        if (
            st.session_state.get(firma_filtro_key) is not None
            and st.session_state[firma_filtro_key] != firma_filtro
        ):
            st.session_state.pop(editor_key, None)

        for indice, documento in enumerate(documentos):
            df_miembros.loc[indice, "Asistió"] = borrador.get(
                documento, False
            )
        df_visible = filtrar_miembros(
            df_miembros, consulta, filtro_asistencia
        )

        total_presentes_hoy = sum(
            bool(borrador.get(documento, False)) for documento in documentos
        )
        total_miembros = len(documentos)
        porcentaje_asistencia = (
            total_presentes_hoy / total_miembros * 100
            if total_miembros
            else 0
        )
        metricas = st.columns(3)
        metricas[0].metric(
            "Presentes", total_presentes_hoy, f"de {total_miembros} miembros"
        )
        metricas[1].metric(
            "Pendientes", total_miembros - total_presentes_hoy
        )
        metricas[2].metric("Asistencia", f"{porcentaje_asistencia:.1f}%")

        st.subheader("Lista de miembros")
        st.caption(
            "Orden alfabético por nombre. Los cambios se conservan al buscar "
            "o filtrar y se guardan al confirmar."
        )
        ids_visibles = df_visible["ID"].tolist()
        st.session_state[ids_visibles_key] = ids_visibles
        st.session_state[firma_filtro_key] = firma_filtro
        df_editado = st.data_editor(
            df_visible,
            width="stretch",
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Asistió": st.column_config.CheckboxColumn(
                    "¿Asistió?", default=False
                ),
                "Congregación": st.column_config.TextColumn(
                    "Congregación", disabled=True
                ),
                "ID": st.column_config.TextColumn(
                    "Cédula / Número de Documento", disabled=True
                ),
                "Nombres": st.column_config.TextColumn("Nombres", disabled=True),
                "Apellidos": st.column_config.TextColumn(
                    "Apellidos", disabled=True
                ),
            },
            key=editor_key,
        )
        for _, fila in df_editado.iterrows():
            borrador[str(fila["ID"])] = bool(fila["Asistió"])

        cambios_pendientes = contar_cambios(
            estados_originales, borrador, documentos
        )
        st.caption(
            "Registros nuevos o cambios pendientes: "
            f"{cambios_pendientes}."
        )

        if hay_documentos_duplicados:
            st.warning("El guardado está deshabilitado hasta corregir duplicados.")

        confirmar_key = (
            f"confirmar_{fecha_seleccionada}_"
            f"{st.session_state.get(f'generacion_guardado_{fecha_seleccionada}', 0)}"
        )
        confirmar = st.checkbox(
            f"Confirmo guardar {cambios_pendientes} registros para "
            f"{fecha_seleccionada.strftime('%d/%m/%Y')}",
            key=confirmar_key,
            disabled=cambios_pendientes == 0 or hay_documentos_duplicados,
        )

        datos_reporte = df_miembros.copy()
        datos_reporte["Asistió"] = [
            bool(borrador.get(documento, False)) for documento in documentos
        ]
        csv_reporte = datos_reporte.to_csv(index=False).encode("utf-8-sig")
        col_guardar, col_exportar = st.columns([1, 1])
        with col_guardar:
            btn_guardar = st.button(
                "Guardar asistencia",
                type="primary",
                icon=":material/save:",
                width="stretch",
                disabled=(
                    not confirmar
                    or cambios_pendientes == 0
                    or hay_documentos_duplicados
                ),
            )
        with col_exportar:
            st.download_button(
                "Exportar asistencia del día",
                data=csv_reporte,
                file_name=f"asistencia_{fecha_seleccionada.isoformat()}.csv",
                mime="text/csv",
                icon=":material/download:",
                width="stretch",
            )

        if btn_guardar:
            datos_guardar = df_miembros[["ID"]].copy()
            datos_guardar["Asistió"] = [
                bool(borrador.get(documento, False))
                for documento in documentos
            ]
            with st.spinner("Actualizando registros en Neon..."):
                exito, resultado = guardar_asistencia_en_db(
                    fecha_seleccionada, datos_guardar, estados_originales
                )
                if exito:
                    st.session_state["mensaje_guardado"] = (
                        f"Se guardaron {resultado} registros o cambios. "
                        f"Total presente: {total_presentes_hoy} de {total_miembros}."
                    )
                    st.session_state[f"generacion_guardado_{fecha_seleccionada}"] = (
                        st.session_state.get(
                            f"generacion_guardado_{fecha_seleccionada}", 0
                        )
                        + 1
                    )
                    st.rerun()
                else:
                    st.error(f"Error al guardar: {resultado}")

        with st.expander("Historial de asistencia"):
            fecha_inicio = st.date_input(
                "Mostrar historial desde",
                value=date.today() - timedelta(days=90),
                max_value=date.today(),
                key="periodo_historial",
            )
            fecha_fin = date.today()
            try:
                resumen_historial = obtener_resumen_historial(
                    fecha_inicio, fecha_fin
                )
            except Exception as e:
                st.error(f"Error al consultar el historial: {e}")
            else:
                if resumen_historial.empty:
                    st.info("No hay registros en el periodo seleccionado.")
                else:
                    st.dataframe(
                        resumen_historial,
                        width="stretch",
                        hide_index=True,
                    )
                    fecha_historial = st.selectbox(
                        "Consultar detalle del día",
                        options=resumen_historial["Fecha"].tolist(),
                        format_func=lambda valor: valor.strftime("%d/%m/%Y"),
                        key="fecha_detalle_historial",
                    )
                    try:
                        detalle_historial = obtener_detalle_historial(
                            fecha_historial
                        )
                    except Exception as e:
                        st.error(
                            f"Error al consultar el detalle histórico: {e}"
                        )
                    else:
                        detalle_historial = detalle_historial.merge(
                            df_miembros[
                                ["ID", "Nombres", "Apellidos"]
                            ].drop_duplicates("ID"),
                            on="ID",
                            how="left",
                        )
                        detalle_historial["Asistió"] = (
                            detalle_historial["Estado"] == "Presente"
                        )
                        detalle_historial = detalle_historial.sort_values(
                            ["Nombres", "Apellidos", "ID"],
                            key=lambda columna: (
                                columna.fillna("")
                                .astype(str)
                                .str.strip()
                                .str.casefold()
                            ),
                            kind="stable",
                        )
                        estados_historial = dict(
                            zip(
                                detalle_historial["ID"],
                                detalle_historial["Asistió"],
                            )
                        )
                        editor_historial_key = (
                            f"editor_historial_{fecha_historial}"
                        )
                        editado_historial = st.data_editor(
                            detalle_historial[
                                [
                                    "Asistió",
                                    "ID",
                                    "Nombres",
                                    "Apellidos",
                                ]
                            ],
                            width="stretch",
                            hide_index=True,
                            num_rows="fixed",
                            column_config={
                                "Asistió": (
                                    st.column_config.CheckboxColumn(
                                        "¿Asistió?",
                                        default=False,
                                    )
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
                            key=editor_historial_key,
                        )
                        cambios_historial = contar_cambios(
                            estados_historial,
                            dict(
                                zip(
                                    editado_historial["ID"],
                                    editado_historial["Asistió"],
                                )
                            ),
                            editado_historial["ID"].tolist(),
                        )
                        confirmar_historial_key = (
                            f"confirmar_historial_{fecha_historial}_"
                            f"{st.session_state.get(f'generacion_historial_{fecha_historial}', 0)}"
                        )
                        confirmar_historial = st.checkbox(
                            f"Confirmo corregir {cambios_historial} "
                            f"registros del {fecha_historial.strftime('%d/%m/%Y')}",
                            key=confirmar_historial_key,
                            disabled=cambios_historial == 0,
                        )
                        col_corregir, col_exportar_historial = st.columns(2)
                        with col_corregir:
                            guardar_historial = st.button(
                                "Guardar correcciones históricas",
                                type="primary",
                                icon=":material/save:",
                                width="stretch",
                                disabled=(
                                    not confirmar_historial
                                    or cambios_historial == 0
                                ),
                                key=f"guardar_historial_{fecha_historial}",
                            )
                        with col_exportar_historial:
                            st.download_button(
                                "Exportar detalle histórico",
                                data=editado_historial.to_csv(
                                    index=False
                                ).encode("utf-8-sig"),
                                file_name=(
                                    f"historial_{fecha_historial.isoformat()}.csv"
                                ),
                                mime="text/csv",
                                icon=":material/download:",
                                width="stretch",
                            )

                        if guardar_historial:
                            with st.spinner(
                                "Guardando correcciones históricas..."
                            ):
                                exito, resultado = guardar_asistencia_en_db(
                                    fecha_historial,
                                    editado_historial[["ID", "Asistió"]],
                                    estados_historial,
                                )
                            if exito:
                                st.session_state["mensaje_guardado"] = (
                                    f"Se corrigieron {resultado} registros "
                                    f"del {fecha_historial.strftime('%d/%m/%Y')}."
                                )
                                st.session_state[
                                    f"generacion_historial_{fecha_historial}"
                                ] = st.session_state.get(
                                    f"generacion_historial_{fecha_historial}",
                                    0,
                                ) + 1
                                st.rerun()
                            else:
                                st.error(
                                    f"Error al corregir el historial: {resultado}"
                                )