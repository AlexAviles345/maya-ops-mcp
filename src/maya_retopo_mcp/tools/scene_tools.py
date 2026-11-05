"""Herramientas del dominio `scene.*` (`scene.describe`, `scene.list_meshes`)."""

from __future__ import annotations

from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.models.requests import ListMeshesRequest, SceneDescribeRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.tools import execute_bridge_backed_tool
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient


def execute_scene_describe(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Devuelve escena actual, unidades, ejes, FPS, estado modificado, nodos principales y plugins."""
    return execute_bridge_backed_tool(
        tool_name="scene.describe",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=lambda raw: SceneDescribeRequest.from_dict(raw) and {},
    )


def execute_scene_list_meshes(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Devuelve shapes poligonales con conteos V/E/F, tipos de caras, shells, fronteras y BBox."""
    return execute_bridge_backed_tool(
        tool_name="scene.list_meshes",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=lambda raw: ListMeshesRequest.from_dict(raw).to_bridge_params(),
    )
