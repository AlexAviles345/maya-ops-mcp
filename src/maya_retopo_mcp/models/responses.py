"""Contratos de salida y envoltura común de respuesta (Secciones 6 y 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from maya_retopo_mcp.errors import ErrorDetail


def current_iso_timestamp() -> str:
    """Devuelve timestamp ISO-8601 con zona horaria local."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class HealthData:
    """Salida mínima de `maya.health` (Sección 6)."""

    ok: bool
    maya_version: str
    python_version: str
    scene: str | None
    modified: bool
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "maya_version": self.maya_version,
            "python_version": self.python_version,
            "scene": self.scene,
            "modified": self.modified,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class ToolResponseEnvelope:
    """Envoltura uniforme para todas las respuestas de herramientas MCP (Sección 7)."""

    ok: bool
    tool: str
    timestamp: str
    scene: str | None = None
    scene_modified: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    error: ErrorDetail | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        if not self.ok and self.error is not None:
            return {
                "ok": False,
                "tool": self.tool,
                "timestamp": self.timestamp,
                "scene": self.scene,
                "scene_modified": self.scene_modified,
                "error": self.error.to_dict(),
                "warnings": list(self.warnings),
                "errors": [self.error.to_dict(), *self.errors],
                "duration_ms": self.duration_ms,
            }
        return {
            "ok": True,
            "tool": self.tool,
            "timestamp": self.timestamp,
            "scene": self.scene,
            "scene_modified": self.scene_modified,
            "data": dict(self.data),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def success(
        cls,
        *,
        tool: str,
        data: dict[str, Any],
        scene: str | None = None,
        scene_modified: bool = False,
        warnings: list[str] | None = None,
        duration_ms: int = 0,
    ) -> ToolResponseEnvelope:
        return cls(
            ok=True,
            tool=tool,
            timestamp=current_iso_timestamp(),
            scene=scene,
            scene_modified=scene_modified,
            data=data,
            warnings=warnings or [],
            errors=[],
            error=None,
            duration_ms=duration_ms,
        )

    @classmethod
    def failure(
        cls,
        *,
        tool: str,
        error: ErrorDetail,
        scene: str | None = None,
        scene_modified: bool = False,
        warnings: list[str] | None = None,
        duration_ms: int = 0,
    ) -> ToolResponseEnvelope:
        return cls(
            ok=False,
            tool=tool,
            timestamp=current_iso_timestamp(),
            scene=scene,
            scene_modified=scene_modified,
            data={},
            warnings=warnings or [],
            errors=[error.to_dict()],
            error=error,
            duration_ms=duration_ms,
        )
