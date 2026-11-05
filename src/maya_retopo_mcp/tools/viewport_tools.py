"""Herramientas del dominio `viewport.*` (`viewport.capture`)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import SecurityPolicyError
from maya_retopo_mcp.models.requests import ViewportCaptureRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.tools import execute_bridge_backed_tool
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient


def execute_viewport_capture(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
    project_policy: ProjectPathsPolicy | None = None,
) -> ToolResponseEnvelope:
    """
    Captura una imagen del viewport de Maya y garantiza que el estado previo del viewport
    sea restaurado al finalizar (`viewport_state_restored: true`).
    """
    def _build(raw: dict[str, Any] | None) -> dict[str, Any]:
        req = ViewportCaptureRequest.from_dict(raw)
        output_path: str | None = None

        if project_policy is not None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            fname = req.file_name or f"viewport_{req.camera}_{stamp}.png"
            if not fname.lower().endswith(".png"):
                fname = f"{fname}.png"
            candidate = project_policy.reports_dir / fname
            validated = project_policy.validate_write_target(
                str(candidate),
                category="reports",
                allow_overwrite=False,
            )
            output_path = validated.as_posix()
        elif req.file_name is not None:
            raise SecurityPolicyError(
                code="PROJECT_NOT_CONFIGURED",
                message="Para guardar capturas en disco primero debe ejecutar `project.configure`.",
                recoverable=True,
                suggestion="Ejecute `project.configure` o invoque `viewport.capture` sin `file_name`.",
            )

        return {
            "camera": req.camera,
            "width": req.width,
            "height": req.height,
            "wireframe_on_shaded": req.wireframe_on_shaded,
            "isolate": req.isolate,
            "frame_selected": req.frame_selected,
            "output_path": output_path,
        }

    return execute_bridge_backed_tool(
        tool_name="viewport.capture",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=_build,
    )
