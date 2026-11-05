"""Herramientas del dominio `safety.*` (`safety.checkpoint`)."""

from __future__ import annotations

import time
from typing import Any

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError, SecurityPolicyError
from maya_retopo_mcp.models.requests import SafetyCheckpointRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import check_tool_permission
from maya_retopo_mcp.policies.protected_mesh import ConfirmedRolesState, MeshFingerprint
from maya_retopo_mcp.tools import logger
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient


def execute_safety_checkpoint(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
    project_policy: ProjectPathsPolicy | None = None,
    confirmed_roles: ConfirmedRolesState | None = None,
) -> ToolResponseEnvelope:
    """
    Crea una copia recuperable en `backups_dir` antes de una mutación sin sobrescribir
    checkpoints existentes (Sección 6: `safety.checkpoint`).
    """
    start_ns = time.perf_counter_ns()
    tool_name = "safety.checkpoint"

    try:
        check_tool_permission(tool_name, config.mode)
        req = SafetyCheckpointRequest.from_dict(arguments)

        if project_policy is None:
            raise SecurityPolicyError(
                code="PROJECT_NOT_CONFIGURED",
                message="Debe ejecutar `project.configure` antes de crear checkpoints en `backups/`.",
                recoverable=True,
                suggestion="Ejecute `project.configure` primero.",
            )

        if confirmed_roles is None:
            raise SecurityPolicyError(
                code="ROLES_NOT_CONFIRMED",
                message="Debe confirmar los roles (`retopo.confirm_roles`) antes de crear un checkpoint.",
                recoverable=True,
                suggestion="Ejecute `retopo.confirm_roles` para registrar high_poly y retopology.",
            )

        ckpt_file = project_policy.next_version_path(
            req.base_name,
            directory_category="backups",
        )

        bridge_resp = client.send_action(
            tool_name,
            {
                "checkpoint_path": ckpt_file.as_posix(),
                "reason": req.reason,
                "high_poly_dag": confirmed_roles.high_poly.dag_path,
                "retopology_dag": confirmed_roles.retopology.dag_path,
            },
        )
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="CHECKPOINT_CREATION_FAILED",
                message="No fue posible crear el checkpoint en el puente de Maya.",
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

        hp_raw = bridge_resp.data.get("high_poly_fingerprint")
        if isinstance(hp_raw, dict):
            confirmed_roles.high_poly.verify_matches(MeshFingerprint.from_dict(hp_raw))

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
                message="Error interno inesperado al crear el checkpoint.",
                recoverable=True,
            ),
            duration_ms=duration_ms,
        )
