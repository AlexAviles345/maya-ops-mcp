"""Herramientas MCP organizadas por dominio funcional y ejecutor seguro común."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.permissions import check_tool_permission
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient

logger = logging.getLogger("maya_retopo_mcp.tools")


def execute_bridge_backed_tool(
    *,
    tool_name: str,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None,
    build_bridge_params: Callable[[dict[str, Any] | None], dict[str, Any]],
    transform_data: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> ToolResponseEnvelope:
    """
    Ejecuta una herramienta respaldada por `maya_bridge`:
    1) Verifica permisos de modo (`check_tool_permission`).
    2) Valida los argumentos de entrada con `build_bridge_params`.
    3) Despacha la acción por TCP loopback.
    4) Envuelve el resultado o fallo en `ToolResponseEnvelope`.
    """
    start_ns = time.perf_counter_ns()
    try:
        check_tool_permission(tool_name, config.mode)
        bridge_params = build_bridge_params(arguments)
        bridge_resp = client.send_action(tool_name, bridge_params)
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="BRIDGE_EXECUTION_FAILED",
                message=f"El puente de Maya reportó un fallo en {tool_name}.",
                recoverable=True,
                suggestion="Verifique los parámetros o el estado de la escena en Maya.",
            )
            return ToolResponseEnvelope.failure(
                tool=tool_name,
                error=err,
                scene=bridge_resp.scene,
                scene_modified=bridge_resp.scene_modified,
                warnings=bridge_resp.warnings,
                duration_ms=duration_ms,
            )

        data = transform_data(bridge_resp.data) if transform_data else bridge_resp.data
        return ToolResponseEnvelope.success(
            tool=tool_name,
            data=data,
            scene=bridge_resp.scene,
            scene_modified=bridge_resp.scene_modified,
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
                message=f"Error interno inesperado al ejecutar {tool_name}.",
                recoverable=True,
                suggestion="Revise los logs locales del servidor MCP.",
            ),
            duration_ms=duration_ms,
        )
