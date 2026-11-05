"""Pruebas de integración de extremo a extremo para todas las herramientas de Fase 1 (Solo Lectura)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.handlers_read import get_simulated_state, reset_simulated_state
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.server import MayaRetopoMcpServer


class TestPhase1ReadOnlyToolsEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        reset_simulated_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name).resolve()
        (self.project_root / "original").mkdir(parents=True, exist_ok=True)

        self.bridge = MayaBridgeServer(host="127.0.0.1", port=0)
        status = self.bridge.start()
        self.cfg = ServerConfig(
            maya_host="127.0.0.1",
            maya_port=int(status["port"]),
            mode=ServerMode.READ_ONLY,
        )
        self.server = MayaRetopoMcpServer(config=self.cfg)

    def tearDown(self) -> None:
        self.bridge.stop()
        self._tmp.cleanup()
        reset_simulated_state()

    def test_project_configure_creates_internal_dirs_and_rejects_missing_root(self) -> None:
        # 1. Falla si project_root no existe (nunca crea fuera de un project_root existente)
        missing_root = (self.project_root / "inexistente").as_posix()
        fail_env = self.server.call_tool(
            "project.configure",
            {
                "project_root": missing_root,
                "original_dir": f"{missing_root}/original",
                "output_dir": f"{missing_root}/output",
                "reports_dir": f"{missing_root}/reports",
                "backups_dir": f"{missing_root}/backups",
            },
        )
        self.assertFalse(fail_env.ok)
        assert fail_env.error is not None
        self.assertEqual(fail_env.error.code, "PROJECT_ROOT_NOT_FOUND")
        self.assertFalse((self.project_root / "inexistente").exists())

        # 2. Configura correctamente sobre project_root existente
        root_str = self.project_root.as_posix()
        ok_env = self.server.call_tool(
            "project.configure",
            {
                "project_root": root_str,
                "original_dir": f"{root_str}/original",
                "output_dir": f"{root_str}/output",
                "reports_dir": f"{root_str}/reports",
                "backups_dir": f"{root_str}/backups",
            },
        )
        self.assertTrue(ok_env.ok)
        self.assertTrue(ok_env.data["configured"])
        self.assertTrue((self.project_root / "output").is_dir())
        self.assertTrue((self.project_root / "reports").is_dir())
        self.assertTrue((self.project_root / "backups").is_dir())

    def test_scene_describe_and_list_meshes_with_pagination(self) -> None:
        desc_env = self.server.call_tool("scene.describe", {})
        self.assertTrue(desc_env.ok)
        self.assertFalse(desc_env.scene_modified)
        self.assertEqual(desc_env.data["units"]["linear"], "cm")
        self.assertEqual(desc_env.data["units"]["fps"], 24.0)
        self.assertEqual(desc_env.data["mesh_count"], 2)

        # Paginación limit=1
        page1 = self.server.call_tool("scene.list_meshes", {"offset": 0, "limit": 1})
        self.assertTrue(page1.ok)
        self.assertEqual(page1.data["total_count"], 2)
        self.assertTrue(page1.data["has_more"])
        self.assertEqual(len(page1.data["meshes"]), 1)

        # Filtro por nombre
        filtered = self.server.call_tool("scene.list_meshes", {"name_contains": "retopo"})
        self.assertTrue(filtered.ok)
        self.assertEqual(filtered.data["total_count"], 1)
        self.assertEqual(filtered.data["meshes"][0]["transform_dag_path"], "|retopo_cuerpo")

    def test_selection_get_and_truncation_limit(self) -> None:
        get_simulated_state()["selection"] = [f"|retopo_cuerpo.vtx[{i}]" for i in range(10)]
        sel_env = self.server.call_tool("selection.get", {"max_components": 4})
        self.assertTrue(sel_env.ok)
        self.assertFalse(sel_env.scene_modified)
        self.assertEqual(sel_env.data["mode"], "component")
        self.assertEqual(len(sel_env.data["components"]), 4)
        self.assertEqual(sel_env.data["component_count"], 10)
        self.assertTrue(sel_env.data["truncated"])

    def test_retopo_inspection_tools_end_to_end(self) -> None:
        # 1. detect_candidates
        cand_env = self.server.call_tool("retopo.detect_candidates", {})
        self.assertTrue(cand_env.ok)
        self.assertFalse(cand_env.scene_modified)
        self.assertFalse(cand_env.data["roles_confirmed"])
        self.assertEqual(cand_env.data["high_poly_candidates"][0]["dag_path"], "|escultura_ref")
        self.assertEqual(cand_env.data["retopology_candidates"][0]["dag_path"], "|retopo_cuerpo")

        # 2. analyze_mesh
        mesh_env = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|retopo_cuerpo"})
        self.assertTrue(mesh_env.ok)
        self.assertFalse(mesh_env.scene_modified)
        self.assertTrue(mesh_env.data["is_all_quads"])
        self.assertEqual(mesh_env.data["face_types"]["quad_percentage"], 100.0)
        self.assertEqual(mesh_env.data["boundary_edges"]["loop_count"], 2)

        # 3. analyze_symmetry (verifica plano X = 1.25 sin asumir X = 0)
        sym_env = self.server.call_tool("retopo.analyze_symmetry", {"dag_path": "|retopo_cuerpo"})
        self.assertTrue(sym_env.ok)
        self.assertFalse(sym_env.scene_modified)
        self.assertEqual(sym_env.data["recommended_axis"], "X")
        self.assertAlmostEqual(sym_env.data["plane_offset"], 1.25, places=4)
        self.assertEqual(sym_env.data["paired_percentage"], 100.0)
        self.assertEqual(sym_env.data["confidence"], "HIGH")

        # 4. boundary_loops
        loops_env = self.server.call_tool("retopo.boundary_loops", {"dag_path": "|retopo_cuerpo"})
        self.assertTrue(loops_env.ok)
        self.assertFalse(loops_env.scene_modified)
        self.assertEqual(loops_env.data["boundary_loop_count"], 2)
        regions = {lp["suggested_region"] for lp in loops_env.data["loops"]}
        self.assertIn("feet_or_ankles", regions)
        self.assertIn("head_or_neck", regions)

    def test_viewport_capture_restores_state_on_success_and_on_failure(self) -> None:
        root_str = self.project_root.as_posix()
        self.server.call_tool(
            "project.configure",
            {
                "project_root": root_str,
                "original_dir": f"{root_str}/original",
                "output_dir": f"{root_str}/output",
                "reports_dir": f"{root_str}/reports",
                "backups_dir": f"{root_str}/backups",
            },
        )

        # Captura exitosa
        cap_env = self.server.call_tool(
            "viewport.capture",
            {
                "camera": "front",
                "width": 512,
                "height": 512,
                "wireframe_on_shaded": True,
                "isolate": ["|escultura_ref", "|retopo_cuerpo"],
                "frame_selected": True,
                "file_name": "front_check.png",
            },
        )
        self.assertTrue(cap_env.ok)
        self.assertFalse(cap_env.scene_modified)
        self.assertTrue(cap_env.data["viewport_state_restored"])
        img_path = Path(cap_env.data["image_path"])
        self.assertTrue(img_path.exists())
        self.assertTrue(img_path.read_bytes().startswith(b"\x89PNG"))

        # Verificar que el estado simulado del viewport volvió a camera="persp", wireframe_on_shaded=False
        vp_state = get_simulated_state()["viewport"]
        self.assertEqual(vp_state["camera"], "persp")
        self.assertFalse(vp_state["wireframe_on_shaded"])
        self.assertEqual(vp_state["isolated_nodes"], [])

        # Si ocurre un fallo durante la captura, el viewport aún se restaura a su estado previo
        vp_state["fail_during_capture"] = True
        try:
            fail_cap = self.server.call_tool(
                "viewport.capture",
                {
                    "camera": "side",
                    "wireframe_on_shaded": True,
                    "isolate": ["|retopo_cuerpo"],
                },
            )
            self.assertFalse(fail_cap.ok)
            self.assertEqual(vp_state["camera"], "persp")
            self.assertFalse(vp_state["wireframe_on_shaded"])
            self.assertEqual(vp_state["isolated_nodes"], [])
        finally:
            vp_state.pop("fail_during_capture", None)


if __name__ == "__main__":
    unittest.main()
