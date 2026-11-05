"""Pruebas de integración de extremo a extremo para Fase 3 (`safety.checkpoint` y `retopo.preview_region`)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.handlers_read import get_simulated_state, reset_simulated_state
from maya_bridge.topology import MeshGeometrySnapshot
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.server import MayaRetopoMcpServer


class TestPhase3SafePreviewEndToEnd(unittest.TestCase):
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
                mode=ServerMode.PREVIEW,
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

    def test_safety_checkpoint_creates_non_overwriting_backups_with_fingerprints(self) -> None:
        # Antes de configurar proyecto falla con PROJECT_NOT_CONFIGURED
        no_proj = self.server.call_tool("safety.checkpoint", {"reason": "test"})
        self.assertFalse(no_proj.ok)
        assert no_proj.error is not None
        self.assertEqual(no_proj.error.code, "PROJECT_NOT_CONFIGURED")

        self._prepare_project_and_roles()

        ck1 = self.server.call_tool(
            "safety.checkpoint",
            {"reason": "antes_de_manos", "base_name": "micel_ckpt.mb"},
        )
        self.assertTrue(ck1.ok)
        p1 = Path(ck1.data["checkpoint_path"])
        self.assertEqual(p1.name, "micel_ckpt_v001.mb")
        self.assertTrue(p1.exists())
        self.assertEqual(ck1.data["high_poly_fingerprint"]["dag_path"], "|escultura_ref")
        self.assertEqual(ck1.data["retopology_fingerprint"]["dag_path"], "|retopo_cuerpo")

        # Segundo checkpoint incrementa versión a v002 sin sobrescribir v001
        ck2 = self.server.call_tool(
            "safety.checkpoint",
            {"reason": "antes_de_pies", "base_name": "micel_ckpt.mb"},
        )
        self.assertTrue(ck2.ok)
        p2 = Path(ck2.data["checkpoint_path"])
        self.assertEqual(p2.name, "micel_ckpt_v002.mb")
        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())

    def test_preview_region_modifies_validates_captures_and_restores_exact_state(self) -> None:
        self._prepare_project_and_roles()

        # Verificar conteo inicial de |retopo_cuerpo (12 vértices, 8 caras quad)
        before_mesh = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|retopo_cuerpo"})
        self.assertEqual(before_mesh.data["vertex_count"], 12)
        self.assertEqual(before_mesh.data["face_count"], 8)

        # Ejecutar preview de hands_v1
        prev = self.server.call_tool(
            "retopo.preview_region",
            {
                "operation_id": "hands_v1",
                "parameters": {"step_y": 6.0, "scale": 0.9},
                "views": ["front", "side", "top"],
            },
        )
        self.assertTrue(prev.ok)
        self.assertTrue(prev.data["scene_restored"])
        self.assertTrue(prev.data["validation"]["passed"])
        self.assertTrue(prev.data["validation"]["is_all_quads"])
        self.assertEqual(prev.data["proposed_changes"]["vertices_before"], 12)
        self.assertEqual(prev.data["proposed_changes"]["vertices_after"], 16)
        self.assertEqual(prev.data["proposed_changes"]["faces_before"], 8)
        self.assertEqual(prev.data["proposed_changes"]["faces_after"], 12)
        self.assertEqual(len(prev.data["views"]), 3)
        for v_info in prev.data["views"]:
            self.assertTrue(Path(v_info["image_path"]).exists())

        # Confirmar mediante consulta independiente que la escena regresó a 12 vértices y 8 caras
        after_mesh = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|retopo_cuerpo"})
        self.assertEqual(after_mesh.data["vertex_count"], 12)
        self.assertEqual(after_mesh.data["face_count"], 8)
        self.assertIsNotNone(self.server.last_verified_preview)

    def test_preview_region_aborts_if_high_poly_was_modified(self) -> None:
        self._prepare_project_and_roles()

        # Alterar maliciosamente un vértice de la high-poly en el estado de Maya
        sim = get_simulated_state()
        hp_orig: MeshGeometrySnapshot = sim["meshes"][0]
        tampered_verts = list(hp_orig.vertices)
        tampered_verts[0] = (999.0, 999.0, 999.0)
        sim["meshes"][0] = MeshGeometrySnapshot(
            transform_dag_path=hp_orig.transform_dag_path,
            shape_dag_path=hp_orig.shape_dag_path,
            uuid=hp_orig.uuid,
            vertices=tampered_verts,
            faces=hp_orig.faces,
        )

        prev_fail = self.server.call_tool(
            "retopo.preview_region",
            {"operation_id": "feet_v1", "parameters": {}, "views": ["front"]},
        )
        self.assertFalse(prev_fail.ok)
        assert prev_fail.error is not None
        self.assertEqual(prev_fail.error.code, "HIGH_POLY_CHANGED")


if __name__ == "__main__":
    unittest.main()
