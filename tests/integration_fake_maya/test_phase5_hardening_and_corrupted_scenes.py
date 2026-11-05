"""Pruebas de endurecimiento (Fase 5): escenas corruptas/incompletas, límites, sanitización y auditoría."""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.handlers_read import get_simulated_state, reset_simulated_state
from maya_bridge.topology import MeshGeometrySnapshot
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.errors import ErrorDetail, TransportError, sanitize_error_message
from maya_retopo_mcp.server import MayaRetopoMcpServer
from maya_retopo_mcp.transport.protocol import BridgeRequest, decode_bridge_response


class TestPhase5HardeningAndCorruptedScenes(unittest.TestCase):
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

    def test_empty_or_incomplete_scene_handled_gracefully(self) -> None:
        get_simulated_state()["meshes"] = []

        desc = self.server.call_tool("scene.describe", {})
        self.assertTrue(desc.ok)
        self.assertEqual(desc.data["mesh_count"], 0)

        lst = self.server.call_tool("scene.list_meshes", {})
        self.assertTrue(lst.ok)
        self.assertEqual(lst.data["total_count"], 0)
        self.assertEqual(lst.data["meshes"], [])

        cand = self.server.call_tool("retopo.detect_candidates", {})
        self.assertTrue(cand.ok)
        self.assertEqual(cand.data["high_poly_candidates"], [])
        self.assertEqual(cand.data["retopology_candidates"], [])

    def test_corrupted_mesh_with_out_of_bounds_face_indices_does_not_crash(self) -> None:
        corrupted = MeshGeometrySnapshot(
            transform_dag_path="|malla_corrupta",
            shape_dag_path="|malla_corrupta|Shape",
            uuid="CORRUPT-UUID",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
            faces=[
                (0, 1, 2, 3),         # Quad válido
                (0, 1, 99999, 88888), # Índices fuera de rango
                (0, 1),               # Cara degenerada de 2 vértices
            ],
        )
        get_simulated_state()["meshes"].append(corrupted)

        res = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|malla_corrupta"})
        self.assertTrue(res.ok)
        self.assertFalse(res.data["is_all_quads"])
        self.assertFalse(res.data["is_clean_topology"])
        self.assertEqual(res.data["face_types"]["invalid_faces"], 2)

    def test_corrupted_reopen_marks_version_as_rejected_and_rolls_back(self) -> None:
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
        self.server.call_tool(
            "retopo.confirm_roles",
            {"high_poly": "|escultura_ref", "retopology": "|retopo_cuerpo"},
        )
        prev = self.server.call_tool(
            "retopo.preview_region",
            {"operation_id": "feet_v1", "parameters": {"step_y": -8.0}, "views": ["front"]},
        )
        self.assertTrue(prev.ok)

        # Simular que al reabrir el archivo desde disco se corrompe e introduce un triángulo
        def _corrupted_reopen(target_path: Path) -> None:
            sim = get_simulated_state()
            rt_snap: MeshGeometrySnapshot = sim["meshes"][1]
            sim["meshes"][1] = MeshGeometrySnapshot(
                transform_dag_path=rt_snap.transform_dag_path,
                shape_dag_path=rt_snap.shape_dag_path,
                uuid=rt_snap.uuid,
                vertices=rt_snap.vertices,
                faces=[*rt_snap.faces, (0, 1, 2)],
            )

        with patch("maya_bridge.handlers_apply._reopen_scene_file", side_effect=_corrupted_reopen):
            app_fail = self.server.call_tool(
                "retopo.apply_region",
                {"operation_id": "feet_v1", "parameters": {"step_y": -8.0}, "approved": True},
            )

        self.assertFalse(app_fail.ok)
        assert app_fail.error is not None
        self.assertEqual(app_fail.error.code, "REOPEN_VALIDATION_FAILED")

        # Verificar que el archivo en output/ fue renombrado a .rejected y la malla en memoria volvió a 8 caras
        rejected_files = list((self.project_root / "output").glob("*.rejected"))
        self.assertEqual(len(rejected_files), 1)
        mesh_state = self.server.call_tool("retopo.analyze_mesh", {"dag_path": "|retopo_cuerpo"})
        self.assertEqual(mesh_state.data["face_count"], 8)

    def test_payload_size_limits_and_error_sanitization(self) -> None:
        # 1. Límite de tamaño de solicitud/respuesta
        req = BridgeRequest(action="maya.health", params={"data": "x" * 2048})
        with self.assertRaises(TransportError) as ctx1:
            req.to_bytes(max_payload_bytes=1024)
        self.assertEqual(ctx1.exception.detail.code, "REQUEST_PAYLOAD_TOO_LARGE")

        with self.assertRaises(TransportError) as ctx2:
            decode_bridge_response(b"x" * 2048, max_payload_bytes=1024)
        self.assertEqual(ctx2.exception.detail.code, "RESPONSE_PAYLOAD_TOO_LARGE")

        # 2. Sanitización de errores (oculta Traceback y rutas de C:\Users\...)
        raw_msg = (
            r"Fallo en C:\Users\ArtistaSecreto\Documents\escena.mb "
            "\nTraceback (most recent call last):\n  File \"internal.py\", line 42, in run\nRuntimeError: boom"
        )
        sanitized = sanitize_error_message(raw_msg)
        self.assertNotIn("Traceback", sanitized)
        self.assertNotIn("ArtistaSecreto", sanitized)
        self.assertIn("<ruta_local_redactada>", sanitized)

        err_dict = ErrorDetail(code="TEST_ERR", message=raw_msg).to_dict()
        self.assertNotIn("Traceback", err_dict["message"])

    def test_dependency_audit_zero_runtime_third_party_packages(self) -> None:
        pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        runtime_deps = data["project"].get("dependencies", [])
        self.assertEqual(
            runtime_deps,
            [],
            "El servidor MVP no debe requerir dependencias de terceros en producción.",
        )


if __name__ == "__main__":
    unittest.main()
