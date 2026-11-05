"""Contratos de entrada para las herramientas MCP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maya_retopo_mcp.errors import ValidationError


@dataclass(frozen=True)
class HealthRequest:
    """Entrada para `maya.health` (no admite argumentos desconocidos)."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HealthRequest:
        if raw:
            unexpected = ", ".join(sorted(raw.keys()))
            raise ValidationError(
                code="INVALID_ARGUMENTS",
                message=f"`maya.health` no acepta parámetros. Recibidos: {unexpected}.",
                recoverable=True,
                suggestion="Envíe un objeto vacío `{}`.",
            )
        return cls()


@dataclass(frozen=True)
class ProjectConfigureRequest:
    """Entrada para `project.configure` (Sección 5 - Restricciones de rutas)."""

    project_root: str
    original_dir: str
    output_dir: str
    reports_dir: str
    backups_dir: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProjectConfigureRequest:
        required = ("project_root", "original_dir", "output_dir", "reports_dir", "backups_dir")
        missing = [k for k in required if not isinstance(raw.get(k), str) or not str(raw.get(k)).strip()]
        if missing:
            raise ValidationError(
                code="MISSING_REQUIRED_FIELDS",
                message=f"Faltan campos obligatorios en project.configure: {', '.join(missing)}.",
                recoverable=True,
                suggestion="Proporcione rutas absolutas válidas para las 5 carpetas del proyecto.",
            )
        return cls(
            project_root=str(raw["project_root"]).strip(),
            original_dir=str(raw["original_dir"]).strip(),
            output_dir=str(raw["output_dir"]).strip(),
            reports_dir=str(raw["reports_dir"]).strip(),
            backups_dir=str(raw["backups_dir"]).strip(),
        )


@dataclass(frozen=True)
class PreviewRegionRequest:
    """Entrada tipada para `retopo.preview_region`."""

    operation_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    views: list[str] = field(default_factory=lambda: ["front", "side", "top"])
