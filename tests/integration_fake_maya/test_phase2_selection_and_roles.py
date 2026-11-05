"""Pruebas de integración de extremo a extremo para Fase 2 (`selection.set` y `retopo.confirm_roles`)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.handlers_read import reset_simulated_state
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.server import MayaRetopoMcpServer


class TestPhase2SelectionAndRolesEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        reset_simulated_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name).resolve()
        (self.project_root / "original").mkdir(parents=True, exist_ok=True)

        self.bridge = MayaBridgeServer(host="127.0.0.1", port=0)
        self.port = int(self.bridge.start()["port"])

    def tearDown(self) -> None:
        self.bridge.stop()
        self._tmp.cleanup()
        reset_simulated_state()

    def _configure_project(self, server: MayaRetopoMcpServer) -> None:
        root_str = self.project_root.as_posix()
        env = server.call_tool(
            "project.configure",
            {
                "project_root": root_str,
                "original_dir": f"{root_str}/original",
                "output_dir": f"{root_str}/output",
                "reports_dir": f"{root_str}/reports",
                "backups_dir": f"{root_str}/backups",
            },
        )
        self.assertTrue(env.ok)

    def test_phase2_tools_denied_in_read_only_mode(self) -> None:
        ro_server = MayaRetopoMcpServer(
            config=ServerConfig(
                maya_host="127.0.0.1",
                maya_port=self.port,
                mode=ServerMode.READ_ONLY,
            )
        )
        sel_resp = ro_server.call_tool("selection.set", {"items": ["|retopo_cuerpo"]})
        self.assertFalse(sel_resp.ok)
        assert sel_resp.error is not None
        self.assertEqual(sel_resp.error.code, "MODE_PERMISSION_DENIED")

        roles_resp = ro_server.call_tool(
            "retopo.confirm_roles",
            {"high_poly": "|escultura_ref", "retopology": "|retopo_cuerpo"},
        )
        self.assertFalse(roles_resp.ok)
        assert roles_resp.error is not None
        self.assertEqual(roles_resp.error.code, "MODE_PERMISSION_DENIED")

    def test_selection_set_and_node_existence_validation(self) -> None:
        server = MayaRetopoMcpServer(
            config=ServerConfig(
                maya_host="127.0.0.1",
                maya_port=self.port,
                mode=ServerMode.PREVIEW,
            )
        )
        # Selección válida de objetos y componentes
        ok_sel = server.call_tool(
            "selection.set",
            {"items": ["|escultura_ref", "|retopo_cuerpo"]},
        )
        self.assertTrue(ok_sel.ok)
        self.assertFalse(ok_sel.scene_modified)
        self.assertEqual(ok_sel.data["objects"], ["|escultura_ref", "|retopo_cuerpo"])

        # Nodo inexistente debe rechazarse con NODE_NOT_FOUND
        bad_sel = server.call_tool("selection.set", {"items": ["|malla_fantasma"]})
        self.assertFalse(bad_sel.ok)
        assert bad_sel.error is not None
        self.assertEqual(bad_sel.error.code, "NODE_NOT_FOUND")

        # Limpiar selección
        clr_sel = server.call_tool("selection.set", {"clear": True})
        self.assertTrue(clr_sel.ok)
        self.assertEqual(clr_sel.data["mode"], "empty")

    def test_confirm_roles_explicit_and_via_artist_selection_with_versioned_reports(self) -> None:
        server = MayaRetopoMcpServer(
            config=ServerConfig(
                maya_host="127.0.0.1",
                maya_port=self.port,
                mode=ServerMode.PREVIEW,
            )
        )

        # 1. Sin project.configure previo se rechaza para garantizar escritura de reporte
        no_proj = server.call_tool(
            "retopo.confirm_roles",
            {"high_poly": "|escultura_ref", "retopology": "|retopo_cuerpo"},
        )
        self.assertFalse(no_proj.ok)
        assert no_proj.error is not None
        self.assertEqual(no_proj.error.code, "PROJECT_NOT_CONFIGURED")

        self._configure_project(server)

        # 2. Confirmación explícita por DAG paths -> genera roles_confirmation_v001.json
        c1 = server.call_tool(
            "retopo.confirm_roles",
            {"high_poly": "|escultura_ref", "retopology": "|retopo_cuerpo"},
        )
        self.assertTrue(c1.ok)
        self.assertTrue(c1.data["roles_confirmed"])
        self.assertTrue(c1.data["high_poly_protected"])
        report1 = Path(c1.data["report_path"])
        self.assertEqual(report1.name, "roles_confirmation_v001.json")
        self.assertTrue(report1.exists())

        saved_json1 = json.loads(report1.read_text(encoding="utf-8"))
        self.assertEqual(saved_json1["high_poly"]["dag_path"], "|escultura_ref")
        self.assertEqual(saved_json1["retopology"]["dag_path"], "|retopo_cuerpo")
        self.assertIsNotNone(server.confirmed_roles)

        # 3. Confirmación mediante selección activa del artista -> genera roles_confirmation_v002.json sin sobrescribir v001
        server.call_tool("selection.set", {"items": ["|escultura_ref", "|retopo_cuerpo"]})
        c2 = server.call_tool("retopo.confirm_roles", {"use_current_selection": True})
        self.assertTrue(c2.ok)
        self.assertEqual(c2.data["confirmed_via"], "artist_selection")
        report2 = Path(c2.data["report_path"])
        self.assertEqual(report2.name, "roles_confirmation_v002.json")
        self.assertTrue(report1.exists())
        self.assertTrue(report2.exists())


if __name__ == "__main__":
    unittest.main()
