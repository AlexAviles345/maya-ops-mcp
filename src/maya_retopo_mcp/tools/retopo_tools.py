"""Herramientas del dominio `retopo.*` (Fase 1: inspección; Fase 2: confirmación de roles)."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail, MayaRetopoMcpError, SecurityPolicyError
from maya_retopo_mcp.models.requests import (
    AnalyzeMeshRequest,
    AnalyzeSymmetryRequest,
    BoundaryLoopsRequest,
    ConfirmRolesRequest,
    DetectCandidatesRequest,
    PreviewRegionRequest,
)
from maya_retopo_mcp.models.responses import ToolResponseEnvelope, current_iso_timestamp
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import (
    check_tool_permission,
    validate_operation_id,
)
from maya_retopo_mcp.policies.protected_mesh import (
    ConfirmedRolesState,
    MeshFingerprint,
    VerifiedPreviewRecord,
)
from maya_retopo_mcp.tools import execute_bridge_backed_tool, logger
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


def execute_retopo_confirm_roles(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
    project_policy: ProjectPathsPolicy | None = None,
    on_roles_confirmed: Callable[[ConfirmedRolesState], None] | None = None,
) -> ToolResponseEnvelope:
    """
    Confirma los roles `high_poly` y `retopology`, escribe un reporte JSON versionado en `reports_dir`
    y activa la protección de huella estructural sobre la `high_poly` (Sección 6).
    """
    start_ns = time.perf_counter_ns()
    tool_name = "retopo.confirm_roles"

    try:
        check_tool_permission(tool_name, config.mode)
        req = ConfirmRolesRequest.from_dict(arguments)

        if project_policy is None:
            raise SecurityPolicyError(
                code="PROJECT_NOT_CONFIGURED",
                message=(
                    "Antes de confirmar roles debe configurar las carpetas del proyecto con `project.configure` "
                    "para poder guardar el reporte JSON versionado en `reports/`."
                ),
                recoverable=True,
                suggestion="Ejecute `project.configure` primero y vuelva a llamar a `retopo.confirm_roles`.",
            )

        bridge_resp = client.send_action(
            tool_name,
            {
                "high_poly": req.high_poly,
                "retopology": req.retopology,
                "use_current_selection": req.use_current_selection,
            },
        )
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="CONFIRM_ROLES_FAILED",
                message="El puente de Maya reportó un error al confirmar roles.",
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

        hp_fp = MeshFingerprint.from_dict(bridge_resp.data["high_poly"])
        rt_fp = MeshFingerprint.from_dict(bridge_resp.data["retopology"])
        report_file = project_policy.next_version_path(
            "roles_confirmation.json",
            directory_category="reports",
        )

        confirmed_state = ConfirmedRolesState(
            high_poly=hp_fp,
            retopology=rt_fp,
            confirmed_via=str(bridge_resp.data.get("confirmed_via", "explicit_dag_paths")),
            confirmed_at=current_iso_timestamp(),
            report_path=report_file.as_posix(),
            scene=bridge_resp.scene,
        )

        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(confirmed_state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if on_roles_confirmed is not None:
            on_roles_confirmed(confirmed_state)

        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)
        return ToolResponseEnvelope.success(
            tool=tool_name,
            data=confirmed_state.to_dict(),
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
                message="Error interno inesperado al confirmar roles.",
                recoverable=True,
            ),
            duration_ms=duration_ms,
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


def execute_retopo_preview_region(
    *,
    config: ServerConfig,
    client: MayaLoopbackClient,
    arguments: dict[str, Any] | None = None,
    project_policy: ProjectPathsPolicy | None = None,
    confirmed_roles: ConfirmedRolesState | None = None,
    on_preview_verified: Callable[[VerifiedPreviewRecord], None] | None = None,
) -> ToolResponseEnvelope:
    """
    Ejecuta una operación regional registrada dentro de un undo chunk, valida topología,
    captura vistas de comprobación y deshace dejando `scene_restored: true` (Sección 6).
    """
    start_ns = time.perf_counter_ns()
    tool_name = "retopo.preview_region"

    try:
        check_tool_permission(tool_name, config.mode)
        req = PreviewRegionRequest.from_dict(arguments)
        validate_operation_id(req.operation_id)

        if project_policy is None:
            raise SecurityPolicyError(
                code="PROJECT_NOT_CONFIGURED",
                message="Debe configurar el proyecto (`project.configure`) antes de ejecutar un preview.",
                recoverable=True,
                suggestion="Ejecute `project.configure` primero.",
            )

        if confirmed_roles is None:
            raise SecurityPolicyError(
                code="ROLES_NOT_CONFIRMED",
                message="Debe confirmar los roles (`retopo.confirm_roles`) antes de ejecutar un preview.",
                recoverable=True,
                suggestion="Ejecute `retopo.confirm_roles` primero.",
            )

        report_file = project_policy.next_version_path(
            f"preview_{req.operation_id}.json",
            directory_category="reports",
        )
        view_output_paths: dict[str, str] = {}
        for view in req.views:
            img_path = project_policy.reports_dir / f"{report_file.stem}_{view}.png"
            validated_img = project_policy.validate_write_target(
                str(img_path),
                category="reports",
                allow_overwrite=False,
            )
            view_output_paths[view] = validated_img.as_posix()

        bridge_resp = client.send_action(
            tool_name,
            {
                "operation_id": req.operation_id,
                "parameters": req.parameters,
                "views": req.views,
                "view_output_paths": view_output_paths,
                "high_poly_dag": confirmed_roles.high_poly.dag_path,
                "retopology_dag": confirmed_roles.retopology.dag_path,
                "expected_high_poly_hash": confirmed_roles.high_poly.structural_hash,
            },
        )
        duration_ms = max(0, (time.perf_counter_ns() - start_ns) // 1_000_000)

        if not bridge_resp.ok:
            err = bridge_resp.error or ErrorDetail(
                code="PREVIEW_REGION_FAILED",
                message=f"Fallo durante el preview de '{req.operation_id}'.",
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

        result_data = dict(bridge_resp.data)
        result_data["report_path"] = report_file.as_posix()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(result_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if on_preview_verified is not None and result_data.get("scene_restored") is True:
            record = VerifiedPreviewRecord(
                scene=bridge_resp.scene,
                operation_id=req.operation_id,
                parameters=dict(req.parameters),
                high_poly_hash=str(result_data.get("high_poly_hash", confirmed_roles.high_poly.structural_hash)),
                retopology_initial_hash=str(result_data.get("retopology_initial_hash", "")),
                timestamp=current_iso_timestamp(),
            )
            on_preview_verified(record)

        return ToolResponseEnvelope.success(
            tool=tool_name,
            data=result_data,
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
                message="Error interno inesperado en retopo.preview_region.",
                recoverable=True,
            ),
            duration_ms=duration_ms,
        )
