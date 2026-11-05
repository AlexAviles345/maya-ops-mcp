"""Herramientas del dominio `maya.*` (`maya.health`)."""

from __future__ import annotations

import logging
import time
from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError
from maya_retopo_mcp.models.requests import HealthRequest
from maya_retopo_mcp.models.responses import HealthData, ToolResponseEnvelope
from maya_retopo_mcp.policies.permissions import check_tool_permission
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient

logger = logging.getLogger("maya_retopo_mcp.tools.maya")


def execute_maya_health(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """
    Ejecuta `maya.health` (Sección 6).
    Comprueba conexión TCP loopback, versión de Maya y Python, escena actual,
    estado `modified` y modo activo del servidor MCP.
    """
    start_ns = time.perf_counter_ns()
    tool_name = "maya.health"

    try:
        check_tool_permission(tool_name, config.mode)
        HealthRequest.from_dict(arguments)

        bridge_resp = client.send_action(tool_name, {})
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="MAYA_HEALTH_FAILED",
                message="El puente de Maya reportó un fallo en maya.health.",
                recoverable=True,
                suggestion="Verifique el estado de Maya y reintente.",
            )
            return ToolResponseEnvelope.failure(
                tool=tool_name,
                error=err,
                scene=bridge_resp.scene,
                scene_modified=bridge_resp.scene_modified,
                warnings=bridge_resp.warnings,
                duration_ms=duration_ms,
            )

        raw_data = bridge_resp.data
        scene_path = raw_data.get("scene", bridge_resp.scene)
        is_modified = bool(raw_data.get("modified", bridge_resp.scene_modified))

        health_data = HealthData(
            ok=bool(raw_data.get("ok", True)),
            maya_version=str(raw_data.get("maya_version", "2027")),
            python_version=str(raw_data.get("python_version", "3.x")),
            scene=str(scene_path) if scene_path else None,
            modified=is_modified,
            mode=config.mode.value,
        )

        return ToolResponseEnvelope.success(
            tool=tool_name,
            data=health_data.to_dict(),
            scene=health_data.scene,
            scene_modified=health_data.modified,
            warnings=bridge_resp.warnings,
            duration_ms=duration_ms,
        )
    except MayaRetopoMcpError as exc:
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
        logger.warning(
            "Error controlado en %s: %s",
            tool_name,
            exc.detail.message,
            extra={"tool": tool_name, "error_code": exc.detail.code},
        )
        return ToolResponseEnvelope.failure(
            tool=tool_name,
            error=exc.detail,
            duration_ms=duration_ms,
        )
    except Exception:
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
        logger.exception("Excepción inesperada en %s", tool_name, extra={"tool": tool_name})
        return ToolResponseEnvelope.failure(
            tool=tool_name,
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="Error interno inesperado al ejecutar maya.health.",
                recoverable=True,
                suggestion="Revise los logs locales del servidor MCP.",
            ),
            duration_ms=duration_ms,
        )

