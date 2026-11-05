"""Herramientas del dominio `retopo.*` (Fase 1: inspección, candidatos, topología, simetría y fronteras)."""

from __future__ import annotations

from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.models.requests import (
    AnalyzeMeshRequest,
    AnalyzeSymmetryRequest,
    BoundaryLoopsRequest,
    DetectCandidatesRequest,
)
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.tools import execute_bridge_backed_tool
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient


def execute_retopo_detect_candidates(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Clasifica candidatos a high-poly y retopología usando evidencia, sin confirmar roles."""
    return execute_bridge_backed_tool(
        tool_name="retopo.detect_candidates",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=lambda raw: DetectCandidatesRequest.from_dict(raw) and {},
    )


def execute_retopo_analyze_mesh(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Ejecuta el análisis topológico detallado de una malla sin modificar la escena."""
    def _build(raw: dict[str, Any] | None) -> dict[str, Any]:
        req = AnalyzeMeshRequest.from_dict(raw)
        return {
            "dag_path": req.dag_path,
            "coincident_tolerance": req.coincident_tolerance,
        }

    return execute_bridge_backed_tool(
        tool_name="retopo.analyze_mesh",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=_build,
    )


def execute_retopo_analyze_symmetry(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Evalúa X, Y y Z como posibles planos bilaterales de simetría sin asumir X = 0."""
    def _build(raw: dict[str, Any] | None) -> dict[str, Any]:
        req = AnalyzeSymmetryRequest.from_dict(raw)
        return {
            "dag_path": req.dag_path,
            "tolerance": req.tolerance,
        }

    return execute_bridge_backed_tool(
        tool_name="retopo.analyze_symmetry",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=_build,
    )


def execute_retopo_boundary_loops(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
) -> ToolResponseEnvelope:
    """Devuelve grupos de bordes abiertos, tipo topológico y región anatómica sugerida."""
    def _build(raw: dict[str, Any] | None) -> dict[str, Any]:
        req = BoundaryLoopsRequest.from_dict(raw)
        return {"dag_path": req.dag_path}

    return execute_bridge_backed_tool(
        tool_name="retopo.boundary_loops",
        config=config,
        client=client,
        arguments=arguments,
        build_bridge_params=_build,
    )
