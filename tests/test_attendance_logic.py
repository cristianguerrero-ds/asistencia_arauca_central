import unittest

import pandas as pd

from attendance_logic import (
    aplicar_ediciones_editor,
    contar_cambios,
    filtrar_cambios_asistencia,
    filtrar_miembros,
    obtener_documentos_duplicados,
)


class AttendanceLogicTests(unittest.TestCase):
    def setUp(self):
        self.members = pd.DataFrame(
            [
                ["001", "Ana", "Lopez", True],
                ["002", "Luis", "Perez", False],
                ["003", "Ana Maria", "Rojas", False],
            ],
            columns=["ID", "Nombres", "Apellidos", "Asistió"],
        )

    def test_search_is_case_insensitive_and_literal(self):
        self.assertEqual(
            filtrar_miembros(self.members, "ANA", "Todos")["ID"].tolist(),
            ["001", "003"],
        )
        self.assertTrue(
            filtrar_miembros(self.members, ".", "Todos").empty
        )
        self.assertEqual(
            filtrar_miembros(self.members, "002", "Todos")["ID"].tolist(),
            ["002"],
        )

    def test_attendance_filter(self):
        self.assertEqual(
            filtrar_miembros(self.members, "", "Presentes")["ID"].tolist(),
            ["001"],
        )
        self.assertEqual(
            filtrar_miembros(self.members, "", "Pendientes")["ID"].tolist(),
            ["002", "003"],
        )

    def test_editor_changes_are_applied_to_visible_documents_only(self):
        draft = {"001": False, "002": False, "003": True}
        aplicar_ediciones_editor(
            {"edited_rows": {"1": {"Asistió": False}}},
            ["001", "003"],
            draft,
        )
        self.assertEqual(draft, {"001": False, "002": False, "003": False})

        aplicar_ediciones_editor(
            {"edited_rows": {0: {"Asistió": True}}},
            ["001", "003"],
            draft,
        )
        self.assertEqual(draft["001"], True)
        self.assertEqual(draft["002"], False)
        self.assertEqual(draft["003"], False)

    def test_changed_count_includes_missing_snapshot_records(self):
        original = {"001": False, "002": True}
        draft = {"001": True, "002": True, "003": True}
        self.assertEqual(
            contar_cambios(original, draft, ["001", "002", "003"]), 2
        )

    def test_only_changed_rows_are_selected_for_saving(self):
        edited = pd.DataFrame(
            [
                ["001", True],
                ["002", True],
                ["003", False],
            ],
            columns=["ID", "Asistió"],
        )
        changes = filtrar_cambios_asistencia(
            edited, {"001": False, "002": True, "003": True}
        )
        self.assertEqual(changes["ID"].tolist(), ["001", "003"])

    def test_first_save_records_absent_members_for_complete_history(self):
        edited = pd.DataFrame(
            [["001", False], ["002", False]],
            columns=["ID", "Asistió"],
        )
        changes = filtrar_cambios_asistencia(edited, {})
        self.assertEqual(changes["ID"].tolist(), ["001", "002"])

    def test_duplicate_document_detection(self):
        members = pd.DataFrame(
            {"ID": ["001", "002", "001", "003", "002"]}
        )
        self.assertEqual(
            set(obtener_documentos_duplicados(members)), {"001", "002"}
        )


if __name__ == "__main__":
    unittest.main()
