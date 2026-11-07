import pandas as pd


def filtrar_miembros(df, consulta, filtro_asistencia):
    resultado = df
    consulta = consulta.strip().casefold()
    if consulta:
        coincidencias = (
            resultado["ID"].fillna("").astype(str).str.casefold().str.contains(
                consulta, regex=False
            )
            | resultado["Nombres"]
            .fillna("")
            .astype(str)
            .str.casefold()
            .str.contains(consulta, regex=False)
            | resultado["Apellidos"]
            .fillna("")
            .astype(str)
            .str.casefold()
            .str.contains(consulta, regex=False)
        )
        resultado = resultado[coincidencias]

    if filtro_asistencia == "Presentes":
        resultado = resultado[resultado["Asistió"]]
    elif filtro_asistencia == "Pendientes":
        resultado = resultado[~resultado["Asistió"]]
    return resultado


def aplicar_ediciones_editor(estado_editor, documentos_visibles, borrador):
    for indice, cambios in estado_editor.get("edited_rows", {}).items():
        indice = int(indice)
        if (
            0 <= indice < len(documentos_visibles)
            and "Asistió" in cambios
        ):
            borrador[documentos_visibles[indice]] = bool(cambios["Asistió"])


def contar_cambios(estados_originales, borrador, documentos):
    return sum(
        documento not in estados_originales
        or bool(borrador.get(documento, False))
        != bool(estados_originales[documento])
        for documento in documentos
    )


def filtrar_cambios_asistencia(df, estados_originales):
    cambios = df.apply(
        lambda fila: str(fila["ID"]).strip() not in estados_originales
        or bool(fila["Asistió"])
        != bool(estados_originales[str(fila["ID"]).strip()]),
        axis=1,
    )
    return df[cambios]


def obtener_documentos_duplicados(df):
    return df.loc[df["ID"].duplicated(keep=False), "ID"].unique()
