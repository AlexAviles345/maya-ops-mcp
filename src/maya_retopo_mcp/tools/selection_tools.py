"""Herramientas del dominio `selection.*` (`selection.get`)."""

from __future__ import annotations

from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.models.requests import SelectionGetRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.tools import execute_bridge_backed_tool
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient


def execute_selection_get(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Devuelve la selección actual, modo objeto/componente y componentes expandidos con límite."""
    return execute_bridge_backed_tool(
        tool_name="selection.get",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=lambda raw: {
            "max_components": SelectionGetRequest.from_dict(raw).max_components
        },
    )
