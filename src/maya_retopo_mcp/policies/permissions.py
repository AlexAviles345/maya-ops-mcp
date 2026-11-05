"""Políticas de permisos por modo (`READ_ONLY`, `PREVIEW`, `APPLY`) y operaciones registradas."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maya_retopo_mcp.config import ServerMode
from maya_retopo_mcp.errors import SecurityPolicyError

MODE_RANK: dict[ServerMode, int] = {
    ServerMode.READ_ONLY: 0,
    ServerMode.PREVIEW: 1,
    ServerMode.APPLY: 2,
}


@dataclass(frozen=True)
class ToolSecurityMeta:
    """Metadatos declarativos de seguridad para cada herramienta MCP (Sección 6)."""

    name: str
    min_mode: ServerMode
    read_only: bool
    idempotent: bool
    destructive: bool
    description: str

    def to_annotations(self) -> dict[str, Any]:
        return {
            "readOnlyHint": self.read_only,
            "idempotentHint": self.idempotent,
            "destructiveHint": self.destructive,
            "minMode": self.min_mode.value,
        }


TOOL_SECURITY_REGISTRY: dict[str, ToolSecurityMeta] = {
    "maya.health": ToolSecurityMeta(
        name="maya.health",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Comprueba conexión loopback con Maya, versión, escena actual y modo activo.",
    ),
    "project.configure": ToolSecurityMeta(
        name="project.configure",
        min_mode=ServerMode.READ_ONLY,
        read_only=False,
        idempotent=True,
        destructive=False,
        description="Configura y valida las carpetas permitidas del proyecto sin tocar fuera de project_root.",
    ),
    "scene.describe": ToolSecurityMeta(
        name="scene.describe",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Devuelve escena actual, unidades, ejes, FPS, estado modificado y nodos principales.",
    ),
    "scene.list_meshes": ToolSecurityMeta(
        name="scene.list_meshes",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Devuelve shapes poligonales con DAG path, UUID, conteos V/E/F, shells y fronteras.",
    ),
    "selection.get": ToolSecurityMeta(
        name="selection.get",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Devuelve la selección actual y componentes expandidos con límite configurable.",
    ),
    "selection.set": ToolSecurityMeta(
        name="selection.set",
        min_mode=ServerMode.PREVIEW,
        read_only=False,
        idempotent=True,
        destructive=False,
        description="Selecciona objetos o componentes existentes sin modificar geometría.",
    ),
    "retopo.detect_candidates": ToolSecurityMeta(
        name="retopo.detect_candidates",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Clasifica candidatos a high-poly y retopología usando evidencia geométrica.",
    ),
    "retopo.confirm_roles": ToolSecurityMeta(
        name="retopo.confirm_roles",
        min_mode=ServerMode.PREVIEW,
        read_only=False,
        idempotent=True,
        destructive=False,
        description="Confirma roles high_poly y retopology y activa la protección de la high-poly.",
    ),
    "retopo.analyze_mesh": ToolSecurityMeta(
        name="retopo.analyze_mesh",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Análisis topológico determinista de una malla sin modificar la escena.",
    ),
    "retopo.analyze_symmetry": ToolSecurityMeta(
        name="retopo.analyze_symmetry",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Evalúa X, Y y Z como posibles planos bilaterales de simetría.",
    ),
    "retopo.boundary_loops": ToolSecurityMeta(
        name="retopo.boundary_loops",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Devuelve grupos de bordes abiertos y región anatómica sugerida.",
    ),
    "viewport.capture": ToolSecurityMeta(
        name="viewport.capture",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Captura imagen del viewport restaurando el estado previo al finalizar.",
    ),
    "safety.checkpoint": ToolSecurityMeta(
        name="safety.checkpoint",
        min_mode=ServerMode.PREVIEW,
        read_only=False,
        idempotent=False,
        destructive=False,
        description="Crea una copia recuperable en backups/ antes de cualquier mutación.",
    ),
    "retopo.preview_region": ToolSecurityMeta(
        name="retopo.preview_region",
        min_mode=ServerMode.PREVIEW,
        read_only=False,
        idempotent=True,
        destructive=False,
        description="Ejecuta una operación regional registrada dentro de un undo chunk y revierte al final.",
    ),
    "retopo.apply_region": ToolSecurityMeta(
        name="retopo.apply_region",
        min_mode=ServerMode.APPLY,
        read_only=False,
        idempotent=False,
        destructive=True,
        description="Aplica una operación regional previamente previsualizada y guarda nueva versión.",
    ),
    "retopo.validate": ToolSecurityMeta(
        name="retopo.validate",
        min_mode=ServerMode.READ_ONLY,
        read_only=True,
        idempotent=True,
        destructive=False,
        description="Ejecuta la auditoría final de retopología sin modificar la escena.",
    ),
    "scene.save_version": ToolSecurityMeta(
        name="scene.save_version",
        min_mode=ServerMode.APPLY,
        read_only=False,
        idempotent=False,
        destructive=False,
        description="Guarda una copia nueva con incremento de versión en output/.",
    ),
}


def check_tool_permission(tool_name: str, current_mode: ServerMode) -> ToolSecurityMeta:
    """Verifica que la herramienta exista y esté autorizada en el modo actual del servidor."""
    meta = TOOL_SECURITY_REGISTRY.get(tool_name)
    if meta is None:
        raise SecurityPolicyError(
            code="UNKNOWN_TOOL",
            message=f"La herramienta '{tool_name}' no está registrada en el catálogo de seguridad.",
            recoverable=False,
            suggestion="Consulte la lista de herramientas publicadas por el servidor MCP.",
        )

    if MODE_RANK[current_mode] < MODE_RANK[meta.min_mode]:
        raise SecurityPolicyError(
            code="MODE_PERMISSION_DENIED",
            message=(
                f"La herramienta '{tool_name}' requiere modo '{meta.min_mode.value}', "
                f"pero el servidor está en '{current_mode.value}'."
            ),
            recoverable=True,
            suggestion=f"Cambie explícitamente el modo a '{meta.min_mode.value}' cuando corresponda.",
        )

    return meta


def load_allowed_operations(registry_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Carga el registro estático de operaciones regionales permitidas (`operations/registry.json`)."""
    if registry_path is None:
        repo_root = Path(__file__).resolve().parents[3]
        registry_path = repo_root / "operations" / "registry.json"

    if not registry_path.exists():
        raise SecurityPolicyError(
            code="OPERATIONS_REGISTRY_MISSING",
            message=f"No se encontró el archivo de registro de operaciones en '{registry_path}'.",
            recoverable=False,
            suggestion="Verifique que operations/registry.json exista en el repositorio.",
        )

    with registry_path.open("r", encoding="utf-8") as fh:
        raw_data = json.load(fh)

    operations = raw_data.get("operations", {})
    if not isinstance(operations, dict):
        raise SecurityPolicyError(
            code="INVALID_OPERATIONS_REGISTRY",
            message="El formato de operations/registry.json es inválido.",
            recoverable=False,
        )
    return operations


def validate_operation_id(
    operation_id: str,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Valida que `operation_id` corresponda a un handler local conocido y habilitado."""
    operations = load_allowed_operations(registry_path)
    op_entry = operations.get(operation_id)
    if op_entry is None or not op_entry.get("enabled", False):
        allowed_list = ", ".join(sorted(k for k, v in operations.items() if v.get("enabled", False)))
        raise SecurityPolicyError(
            code="UNREGISTERED_OPERATION",
            message=f"La operación regional '{operation_id}' no está permitida ni registrada.",
            recoverable=True,
            suggestion=f"Use uno de los identificadores registrados: {allowed_list}.",
        )
    return dict(op_entry)

