"""Pruebas unitarias de configuración, rutas, permisos, huella high-poly y contratos JSON."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.errors import (
    ErrorDetail,
    HighPolyChangedError,
    SecurityPolicyError,
    ValidationError,
)
from maya_retopo_mcp.models.requests import HealthRequest, ProjectConfigureRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import (
    check_tool_permission,
    validate_operation_id,
)
from maya_retopo_mcp.policies.protected_mesh import MeshFingerprint


class TestConfigAndLoopbackPolicy(unittest.TestCase):
    def test_default_mode_is_read_only(self) -> None:
        cfg = ServerConfig()
        self.assertEqual(cfg.mode, ServerMode.READ_ONLY)
        self.assertEqual(cfg.maya_host, "127.0.0.1")

    def test_non_loopback_host_is_rejected(self) -> None:
        for bad_host in ("0.0.0.0", "192.168.1.50", "10.0.0.1", "example.com"):
            with self.assertRaises(SecurityPolicyError) as ctx:
                ServerConfig(maya_host=bad_host)
            self.assertEqual(ctx.exception.detail.code, "NON_LOOPBACK_FORBIDDEN")

    def test_external_package_never_imports_maya_cmds(self) -> None:
        src_root = Path(__file__).resolve().parents[2] / "src" / "maya_retopo_mcp"
        for py_file in src_root.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name.startswith("maya"),
                            f"Importación prohibida de '{alias.name}' en {py_file}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(
                        node.module.startswith("maya."),
                        f"Importación prohibida de '{node.module}' en {py_file}",
                    )


class TestProjectPathsPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.orig = self.root / "original"
        self.out = self.root / "output"
        self.rep = self.root / "reports"
        self.bak = self.root / "backups"
        for folder in (self.orig, self.out, self.rep, self.bak):
            folder.mkdir(parents=True, exist_ok=True)

        self.policy = ProjectPathsPolicy.from_raw(
            project_root=str(self.root),
            original_dir=str(self.orig),
            output_dir=str(self.out),
            reports_dir=str(self.rep),
            backups_dir=str(self.bak),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reject_write_inside_original_dir(self) -> None:
        target = self.orig / "personaje_base.mb"
        with self.assertRaises(SecurityPolicyError) as ctx:
            self.policy.validate_write_target(str(target), category="output")
        self.assertEqual(ctx.exception.detail.code, "ORIGINAL_DIR_READ_ONLY")

    def test_reject_traversal_and_unc_and_shell_chars(self) -> None:
        traversal_path = str(self.out) + "/../original/hack.mb"
        with self.assertRaises(SecurityPolicyError) as ctx1:
            self.policy.validate_write_target(traversal_path, category="output")
        self.assertEqual(ctx1.exception.detail.code, "PATH_TRAVERSAL_FORBIDDEN")

        with self.assertRaises(SecurityPolicyError) as ctx2:
            self.policy.validate_write_target(r"\\server\share\scene.mb", category="output")
        self.assertEqual(ctx2.exception.detail.code, "UNC_PATH_FORBIDDEN")

        with self.assertRaises(SecurityPolicyError) as ctx3:
            self.policy.validate_write_target(str(self.out / "scene;rm.mb"), category="output")
        self.assertEqual(ctx3.exception.detail.code, "SHELL_PATH_FORBIDDEN")

    def test_version_increment_and_no_overwrite(self) -> None:
        v1 = self.policy.next_version_path("micel.mb", directory_category="output")
        self.assertEqual(v1.name, "micel_v001.mb")
        v1.write_text("dummy scene v1", encoding="utf-8")

        # Intentar sobrescribir v1 debe fallar
        with self.assertRaises(SecurityPolicyError) as ctx:
            self.policy.validate_write_target(str(v1), category="output", allow_overwrite=False)
        self.assertEqual(ctx.exception.detail.code, "FILE_ALREADY_EXISTS")

        # El siguiente versionado salta automáticamente a v002
        v2 = self.policy.next_version_path(str(v1), directory_category="output")
        self.assertEqual(v2.name, "micel_v002.mb")


class TestPermissionsAndOperationsPolicy(unittest.TestCase):
    def test_mode_permissions_matrix(self) -> None:
        # En READ_ONLY se permite maya.health y scene.describe, pero NO selection.set ni apply_region
        check_tool_permission("maya.health", ServerMode.READ_ONLY)
        check_tool_permission("scene.describe", ServerMode.READ_ONLY)

        with self.assertRaises(SecurityPolicyError) as ctx1:
            check_tool_permission("selection.set", ServerMode.READ_ONLY)
        self.assertEqual(ctx1.exception.detail.code, "MODE_PERMISSION_DENIED")

        with self.assertRaises(SecurityPolicyError) as ctx2:
            check_tool_permission("retopo.apply_region", ServerMode.PREVIEW)
        self.assertEqual(ctx2.exception.detail.code, "MODE_PERMISSION_DENIED")

        # En APPLY se permite retopo.apply_region
        meta = check_tool_permission("retopo.apply_region", ServerMode.APPLY)
        self.assertTrue(meta.destructive)

    def test_allowed_operations_registry(self) -> None:
        for op_id in ("feet_v1", "hands_v1", "head_face_v1"):
            entry = validate_operation_id(op_id)
            self.assertEqual(entry["operation_id"], op_id)

        with self.assertRaises(SecurityPolicyError) as ctx:
            validate_operation_id("arbitrary_python_exec")
        self.assertEqual(ctx.exception.detail.code, "UNREGISTERED_OPERATION")


class TestProtectedMeshFingerprint(unittest.TestCase):
    def test_high_poly_fingerprint_detects_mutation(self) -> None:
        bbox = (-10.0, 0.0, -5.0, 10.0, 180.0, 5.0)
        h1 = MeshFingerprint.compute_hash(
            dag_path="|escultura_high",
            uuid="1111-2222-3333",
            vertex_count=250000,
            edge_count=500000,
            face_count=250000,
            bounding_box=bbox,
        )
        fp_original = MeshFingerprint(
            dag_path="|escultura_high",
            uuid="1111-2222-3333",
            vertex_count=250000,
            edge_count=500000,
            face_count=250000,
            bounding_box=bbox,
            structural_hash=h1,
        )
        # Misma huella pasa sin error
        fp_original.verify_matches(MeshFingerprint.from_dict(fp_original.to_dict()))

        # Si cambia el conteo de vértices o el bounding box, lanza HighPolyChangedError
        fp_modified = MeshFingerprint(
            dag_path="|escultura_high",
            uuid="1111-2222-3333",
            vertex_count=249999,
            edge_count=500000,
            face_count=250000,
            bounding_box=bbox,
            structural_hash=h1,
        )
        with self.assertRaises(HighPolyChangedError) as ctx:
            fp_original.verify_matches(fp_modified)
        self.assertEqual(ctx.exception.detail.code, "HIGH_POLY_CHANGED")


class TestSchemasAndResponseEnvelope(unittest.TestCase):
    def test_health_request_rejects_extra_fields(self) -> None:
        HealthRequest.from_dict({})
        with self.assertRaises(ValidationError) as ctx:
            HealthRequest.from_dict({"exec": "import os"})
        self.assertEqual(ctx.exception.detail.code, "INVALID_ARGUMENTS")

    def test_project_configure_request_validation(self) -> None:
        with self.assertRaises(ValidationError):
            ProjectConfigureRequest.from_dict({"project_root": "C:/p"})

    def test_response_envelope_contracts(self) -> None:
        ok_env = ToolResponseEnvelope.success(
            tool="maya.health",
            data={"ok": True, "maya_version": "2027"},
            scene="C:/proyecto/output/escena_v001.mb",
            scene_modified=False,
            duration_ms=15,
        ).to_dict()
        self.assertTrue(ok_env["ok"])
        self.assertEqual(ok_env["tool"], "maya.health")
        self.assertFalse(ok_env["scene_modified"])

        fail_env = ToolResponseEnvelope.failure(
            tool="retopo.preview_region",
            error=ErrorDetail(
                code="HIGH_POLY_CHANGED",
                message="La escultura protegida cambio durante la operacion.",
                recoverable=True,
                suggestion="Restaure el checkpoint y revise el handler regional.",
            ),
        ).to_dict()
        self.assertFalse(fail_env["ok"])
        self.assertEqual(fail_env["error"]["code"], "HIGH_POLY_CHANGED")


if __name__ == "__main__":
    unittest.main()

