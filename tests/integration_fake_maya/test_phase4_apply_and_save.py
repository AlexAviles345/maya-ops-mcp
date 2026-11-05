"""Pruebas de integración de extremo a extremo para Fase 4 (`retopo.validate`, `retopo.apply_region`, `scene.save_version`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.handlers_read import get_simulated_state, reset_simulated_state
from maya_bridge.topology import MeshGeometrySnapshot
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.server import MayaRetopoMcpServer


class TestPhase4ApplyAndSaveEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        reset_simulated_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name).resolve()
        (self.project_root / "original").mkdir(parents=True, exist_ok=True)

        self.bridge = MayaBridgeServer(host="127.0.0.1", port=0)
        self.port = int(self.bridge.start()["port"])
        self.server = MayaRetopoMcpServer(
            config=ServerConfig(
                maya_host="127.0.0.1",
                maya_port=self.port,
                mode=ServerMode.APPLY,
            )
        )

    def tearDown(self) -> None:
        self.bridge.stop()
        self._tmp.cleanup()
        reset_simulated_state()

    def _prepare_project_and_roles(self) -> None:
        root_str = self.project_root.as_posix()
        c_proj = self.server.call_tool(
            "project.configure",
            {
                "project_root": root_str,
                "original_dir": f"{root_str}/original",
                "output_dir": f"{root_str}/output",
                "reports_dir": f"{root_str}/reports",
                "backups_dir": f"{root_str}/backups",
            },
        )
        self.assertTrue(c_proj.ok)

        c_roles = self.server.call_tool(
            "retopo.confirm_roles",
            {"high_poly": "|escultura_ref", "retopology": "|retopo_cuerpo"},
        )
        self.assertTrue(c_roles.ok)

    def test_retopo_validate_reports_all_individual_checks_without_hiding_partial_errors(self) -> None:
        self._prepare_project_and_roles()

        # 1. Malla limpia inicial pasa todas las comprobaciones
        val_ok = self.server.call_tool("retopo.validate", {})
        self.assertTrue(val_ok.ok)
        self.assertTrue(val_ok.data["passed"])
        self.assertEqual(val_ok.data["failed_checks"], [])
        self.assertEqual(len(val_ok.data["checks"]), 8)

        # 2. Introducir simultáneamente un triángulo y un vértice coincidente -> ambos fallos se reportan
        sim = get_simulated_state()
        rt_orig: MeshGeometrySnapshot = sim["meshes"][1]
        dirty_verts = [*rt_orig.vertices, rt_orig.vertices[0]]  # Vértice coincidente con 0
        dirty_faces = [*rt_orig.faces, (0, 1, 2)]  # Triángulo adicional
        sim["meshes"][1] = MeshGeometrySnapshot(
            transform_dag_path=rt_orig.transform_dag_path,
            shape_dag_path=rt_orig.shape_dag_path,
            uuid=rt_orig.uuid,
            vertices=dirty_verts,
            faces=dirty_faces,
        )

        val_dirty = self.server.call_tool("retopo.validate", {})
        self.assertTrue(val_dirty.ok)
        self.assertFalse(val_dirty.data["passed"])
        self.assertIn("quads_only", val_dirty.data["failed_checks"])
        self.assertIn("no_coincident_vertices", val_dirty.data["failed_checks"])

    def test_apply_region_enforces_preview_and_executes_full_verified_pipeline(self) -> None:
        self._prepare_project_and_roles()

        # 1. Sin approved=true se rechaza
        no_app = self.server.call_tool(
            "retopo.apply_region",
            {"operation_id": "hands_v1", "parameters": {}, "approved": False},
        )
        self.assertFalse(no_app.ok)
        assert no_app.error is not None
        self.assertEqual(no_app.error.code, "EXPLICIT_APPROVAL_REQUIRED")

        # 2. Sin preview previo se rechaza con PREVIEW_REQUIRED_BEFORE_APPLY
        no_prev = self.server.call_tool(
            "retopo.apply_region",
            {"operation_id": "hands_v1", "parameters": {"step_y": 6.0}, "approved": True},
        )
        self.assertFalse(no_prev.ok)
        assert no_prev.error is not None
        self.assertEqual(no_prev.error.code, "PREVIEW_REQUIRED_BEFORE_APPLY")

        # 3. Ejecutar preview de hands_v1
        prev = self.server.call_tool(
            "retopo.preview_region",
            {
                "operation_id": "hands_v1",
                "parameters": {"step_y": 6.0, "scale": 0.9},
                "views": ["front"],
            },
        )
        self.assertTrue(prev.ok)

        # 4. Intentar apply con parámetros distintos a los del preview se rechaza
        mismatch = self.server.call_tool(
            "retopo.apply_region",
            {
                "operation_id": "hands_v1",
                "parameters": {"step_y": 99.0, "scale": 0.9},
                "approved": True,
            },
        )
        self.assertFalse(mismatch.ok)
        assert mismatch.error is not None
        self.assertEqual(mismatch.error.code, "PREVIEW_REQUIRED_BEFORE_APPLY")

        # 5. Ejecutar apply con los mismos parámetros del preview
        app = self.server.call_tool(
            "retopo.apply_region",
            {
                "operation_id": "hands_v1",
                "parameters": {"step_y": 6.0, "scale": 0.9},
                "approved": True,
            },
        )
        self.assertTrue(app.ok)
        self.assertTrue(app.data["applied"])
        self.assertTrue(app.data["reopened_and_revalidated"])
        self.assertTrue(app.data["validation"]["passed"])
        saved_scene = Path(app.data["saved_scene"])
        self.assertEqual(saved_scene.name, "micel_v002.mb")
        self.assertTrue(saved_scene.exists())
        ckpt_path = Path(app.data["checkpoint"]["checkpoint_path"])
        self.assertTrue(ckpt_path.exists())

        # La escena reabierta tiene ahora 16 vértices y 12 quads
        mesh_after = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|retopo_cuerpo"})
        self.assertEqual(mesh_after.data["vertex_count"], 16)
        self.assertEqual(mesh_after.data["face_count"], 12)
        self.assertTrue(mesh_after.data["is_all_quads"])

    def test_scene_save_version_rejects_original_overwrite_high_poly_change_and_invalid_mesh(self) -> None:
        self._prepare_project_and_roles()

        # 1. Rechaza guardar en original/
        orig_target = (self.project_root / "original" / "micel_v099.mb").as_posix()
        bad_orig = self.server.call_tool("scene.save_version", {"target_path": orig_target})
        self.assertFalse(bad_orig.ok)
        assert bad_orig.error is not None
        self.assertEqual(bad_orig.error.code, "ORIGINAL_DIR_READ_ONLY")

        # 2. Guardado válido incrementa versión a micel_v002.mb
        s1 = self.server.call_tool("scene.save_version", {"base_name": "micel_v001.mb"})
        self.assertTrue(s1.ok)
        saved_file = Path(s1.data["saved_scene"])
        self.assertEqual(saved_file.name, "micel_v002.mb")
        self.assertTrue(saved_file.exists())

        # 3. Rechaza sobrescribir micel_v002.mb existente
        bad_over = self.server.call_tool("scene.save_version", {"target_path": saved_file.as_posix()})
        self.assertFalse(bad_over.ok)
        assert bad_over.error is not None
        self.assertEqual(bad_over.error.code, "FILE_ALREADY_EXISTS")

        # 4. Rechaza guardar si la malla tiene un triángulo (VALIDATION_FAILED)
        sim = get_simulated_state()
        rt_orig: MeshGeometrySnapshot = sim["meshes"][1]
        sim["meshes"][1] = MeshGeometrySnapshot(
            transform_dag_path=rt_orig.transform_dag_path,
            shape_dag_path=rt_orig.shape_dag_path,
            uuid=rt_orig.uuid,
            vertices=rt_orig.vertices,
            faces=[*rt_orig.faces, (0, 1, 2)],
        )
        bad_val = self.server.call_tool("scene.save_version", {"base_name": "micel_v002.mb"})
        self.assertFalse(bad_val.ok)
        assert bad_val.error is not None
        self.assertEqual(bad_val.error.code, "VALIDATION_FAILED")


if __name__ == "__main__":
    unittest.main()
