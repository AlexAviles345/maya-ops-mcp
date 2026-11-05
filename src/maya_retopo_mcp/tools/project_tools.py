"""Herramientas del dominio `project.*` (`project.configure`)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError, SecurityPolicyError
from maya_retopo_mcp.models.requests import ProjectConfigureRequest
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import check_tool_permission

logger = logging.getLogger("maya_retopo_mcp.tools.project")


def execute_project_configure(
    *,
    config: ServerConfig,
    arguments: dict[str, Any] | None,
    on_policy_configured: Callable[[ProjectPathsPolicy], None] | None = None,
) -> ToolResponseEnvelope:
    """
    Configura y valida las carpetas permitidas del proyecto (`project.configure`).
    Nunca crea carpetas fuera de `project_root` ni modifica `original_dir`.
    """
    start_ns = time.perf_counter_ns()
    tool_name = "project.configure"

    try:
        check_tool_permission(tool_name, config.mode)
        req = ProjectConfigureRequest.from_dict(arguments)

        policy = ProjectPathsPolicy.from_raw(
            project_root=req.project_root,
            original_dir=req.original_dir,
            output_dir=req.output_dir,
            reports_dir=req.reports_dir,
            backups_dir=req.backups_dir,
        )

        if not policy.project_root.exists() or not policy.project_root.is_dir():
            raise SecurityPolicyError(
                code="PROJECT_ROOT_NOT_FOUND",
                message=(
                    f"El directorio raíz del proyecto ('{policy.project_root}') no existe. "
                    "Por seguridad no se crean directorios fuera de un project_root existente."
                ),
                recoverable=True,
                suggestion="Cree primero la carpeta raíz del proyecto y vuelva a ejecutar project.configure.",
            )

        # Crear únicamente las subcarpetas de trabajo internas a project_root si no existen
        created_dirs: list[str] = []
        for sub_dir in (policy.output_dir, policy.reports_dir, policy.backups_dir):
            if not sub_dir.exists():
                sub_dir.mkdir(parents=True, exist_ok=True)
                created_dirs.append(sub_dir.as_posix())

        if on_policy_configured is not None:
            on_policy_configured(policy)

        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
        return ToolResponseEnvelope.success(
            tool=tool_name,
            data={
                "configured": True,
                "project_root": policy.project_root.as_posix(),
                "original_dir": policy.original_dir.as_posix(),
                "original_dir_exists": policy.original_dir.exists(),
                "original_read_only": True,
                "output_dir": policy.output_dir.as_posix(),
                "reports_dir": policy.reports_dir.as_posix(),
                "backups_dir": policy.backups_dir.as_posix(),
                "created_internal_dirs": created_dirs,
            },
            scene=None,
            scene_modified=False,
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
                message="Error interno inesperado al configurar el proyecto.",
                recoverable=True,
                suggestion="Revise los logs locales del servidor MCP.",
            ),
            duration_ms=duration_ms,
        )
