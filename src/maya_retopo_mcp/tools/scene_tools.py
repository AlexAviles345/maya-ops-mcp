"""Herramientas del dominio `scene.*` (`scene.describe`, `scene.list_meshes`, `scene.save_version`)."""

from __future__ import annotations

import time
from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError, SecurityPolicyError
from maya_retopo_mcp.models.requests import (
    ListMeshesRequest,
    SceneDescribeRequest,
    SceneSaveVersionRequest,
)
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import check_tool_permission
from maya_retopo_mcp.policies.protected_mesh import ConfirmedRolesState
from maya_retopo_mcp.tools import execute_bridge_backed_tool, logger
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


def execute_scene_save_version(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
    project_policy: ProjectPathsPolicy | None = None,
    confirmed_roles: ConfirmedRolesState | None = None,
) -> ToolResponseEnvelope:
    """
    Guarda una copia nueva con incremento de versión en `output/` rechazando:
    - Rutas en `original/`.
    - Sobrescritura de archivos existentes.
    - Guardado si la high-poly cambió.
    - Guardado si la validación requerida no pasó.
    """
    start_ns = time.perf_counter_ns()
    tool_name = "scene.save_version"

    try:
        check_tool_permission(tool_name, config.mode)
        req = SceneSaveVersionRequest.from_dict(arguments)

        if project_policy is None:
            raise SecurityPolicyError(
                code="PROJECT_NOT_CONFIGURED",
                message="Debe ejecutar `project.configure` antes de guardar escenas.",
                recoverable=True,
                suggestion="Ejecute `project.configure` primero.",
            )

        if confirmed_roles is None:
            raise SecurityPolicyError(
                code="ROLES_NOT_CONFIRMED",
                message="Debe confirmar los roles (`retopo.confirm_roles`) antes de guardar versiones.",
                recoverable=True,
                suggestion="Ejecute `retopo.confirm_roles` primero.",
            )

        if req.target_path is not None:
            out_file = project_policy.validate_write_target(
                req.target_path,
                category="output",
                allow_overwrite=False,
            )
        else:
            base = req.base_name or confirmed_roles.scene or "scene.mb"
            out_file = project_policy.next_version_path(
                base,
                directory_category="output",
            )

        bridge_resp = client.send_action(
            tool_name,
            {
                "output_path": out_file.as_posix(),
                "high_poly_dag": confirmed_roles.high_poly.dag_path,
                "retopology_dag": confirmed_roles.retopology.dag_path,
                "expected_high_poly_hash": confirmed_roles.high_poly.structural_hash,
            },
        )
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="SAVE_VERSION_FAILED",
                message="Fallo al guardar nueva versión de la escena.",
                recoverable=True,
            )
            return ToolResponseEnvelope.failure(
                tool=tool_name,
                error=err,
                scene=bridge_resp.scene,
                scene_modified=bridge_resp.scene_modified,
                warnings=bridge_resp.warnings,
                duration_ms=duration_ms,
            )

        return ToolResponseEnvelope.success(
            tool=tool_name,
            data=bridge_resp.data,
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
                message="Error interno inesperado en scene.save_version.",
                recoverable=True,
            ),
            duration_ms=duration_ms,
        )
