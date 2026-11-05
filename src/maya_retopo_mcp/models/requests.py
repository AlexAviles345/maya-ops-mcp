"""Contratos de entrada tipados y validados para las herramientas MCP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maya_retopo_mcp.errors import ValidationError


def _reject_unexpected_keys(raw: dict[str, Any], allowed: set[str], tool_name: str) -> None:
    unexpected = sorted(set(raw.keys()) - allowed)
    if unexpected:
        raise ValidationError(
            code="INVALID_ARGUMENTS",
            message=f"`{tool_name}` recibió parámetros no reconocidos: {', '.join(unexpected)}.",
            recoverable=True,
            suggestion=f"Parámetros permitidos para {tool_name}: {', '.join(sorted(allowed)) or 'ninguno'}.",
        )


def _validate_dag_path(raw_dag: Any, tool_name: str) -> str:
    if not isinstance(raw_dag, str) or not raw_dag.strip():
        raise ValidationError(
            code="MISSING_DAG_PATH",
            message=f"`{tool_name}` requiere un `dag_path` no vacío.",
            recoverable=True,
            suggestion="Proporcione el DAG path del nodo o shape (por ejemplo '|retopo_cuerpo').",
        )
    dag = raw_dag.strip()
    if any(ch in dag for ch in (";", "\n", "\r", "`", "$")):
        raise ValidationError(
            code="INVALID_DAG_PATH",
            message=f"El `dag_path` '{dag}' contiene caracteres inválidos.",
            recoverable=True,
            suggestion="Use únicamente nombres y rutas DAG válidos de Maya.",
        )
    return dag


@dataclass(frozen=True)
class HealthRequest:
    """Entrada para `maya.health` (no admite argumentos desconocidos)."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> HealthRequest:
        if raw:
            _reject_unexpected_keys(raw, set(), "maya.health")
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
    def from_dict(cls, raw: dict[str, Any] | None) -> ProjectConfigureRequest:
        data = raw or {}
        required = {"project_root", "original_dir", "output_dir", "reports_dir", "backups_dir"}
        _reject_unexpected_keys(data, required, "project.configure")
        missing = [k for k in sorted(required) if not isinstance(data.get(k), str) or not str(data.get(k)).strip()]
        if missing:
            raise ValidationError(
                code="MISSING_REQUIRED_FIELDS",
                message=f"Faltan campos obligatorios en project.configure: {', '.join(missing)}.",
                recoverable=True,
                suggestion="Proporcione rutas absolutas válidas para las 5 carpetas del proyecto.",
            )
        return cls(
            project_root=str(data["project_root"]).strip(),
            original_dir=str(data["original_dir"]).strip(),
            output_dir=str(data["output_dir"]).strip(),
            reports_dir=str(data["reports_dir"]).strip(),
            backups_dir=str(data["backups_dir"]).strip(),
        )


@dataclass(frozen=True)
class SceneDescribeRequest:
    """Entrada para `scene.describe`."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SceneDescribeRequest:
        if raw:
            _reject_unexpected_keys(raw, set(), "scene.describe")
        return cls()


@dataclass(frozen=True)
class ListMeshesRequest:
    """Entrada con soporte de paginación y filtros para `scene.list_meshes`."""

    offset: int = 0
    limit: int = 50
    include_hidden: bool = True
    include_intermediate: bool = False
    name_contains: str = ""
    min_faces: int = 0
    max_faces: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ListMeshesRequest:
        data = raw or {}
        allowed = {
            "offset",
            "limit",
            "include_hidden",
            "include_intermediate",
            "name_contains",
            "min_faces",
            "max_faces",
        }
        _reject_unexpected_keys(data, allowed, "scene.list_meshes")

        offset = int(data.get("offset", 0))
        limit = int(data.get("limit", 50))
        if offset < 0:
            raise ValidationError(
                code="INVALID_PAGINATION",
                message="El parámetro `offset` no puede ser negativo.",
                recoverable=True,
            )
        if limit < 1 or limit > 500:
            raise ValidationError(
                code="INVALID_PAGINATION",
                message="El parámetro `limit` debe estar entre 1 y 500.",
                recoverable=True,
            )
        min_faces = int(data.get("min_faces", 0))
        max_faces_raw = data.get("max_faces")
        max_faces = int(max_faces_raw) if max_faces_raw is not None else None
        if min_faces < 0 or (max_faces is not None and max_faces < min_faces):
            raise ValidationError(
                code="INVALID_FILTER_RANGE",
                message="El rango `min_faces`..`max_faces` es inválido.",
                recoverable=True,
            )

        return cls(
            offset=offset,
            limit=limit,
            include_hidden=bool(data.get("include_hidden", True)),
            include_intermediate=bool(data.get("include_intermediate", False)),
            name_contains=str(data.get("name_contains", "")).strip(),
            min_faces=min_faces,
            max_faces=max_faces,
        )

    def to_bridge_params(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "limit": self.limit,
            "include_hidden": self.include_hidden,
            "include_intermediate": self.include_intermediate,
            "name_contains": self.name_contains,
            "min_faces": self.min_faces,
            "max_faces": self.max_faces,
        }


@dataclass(frozen=True)
class SelectionGetRequest:
    """Entrada para `selection.get`."""

    max_components: int = 500

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SelectionGetRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"max_components"}, "selection.get")
        max_comp = int(data.get("max_components", 500))
        if max_comp < 1 or max_comp > 10_000:
            raise ValidationError(
                code="INVALID_MAX_COMPONENTS",
                message="`max_components` debe estar entre 1 y 10000.",
                recoverable=True,
            )
        return cls(max_components=max_comp)


@dataclass(frozen=True)
class SelectionSetRequest:
    """Entrada para `selection.set` (Fase 2)."""

    items: list[str] = field(default_factory=list)
    clear: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SelectionSetRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"items", "clear"}, "selection.set")
        raw_items = data.get("items") or []
        if not isinstance(raw_items, list):
            raise ValidationError(
                code="INVALID_SELECTION_ITEMS",
                message="El parámetro `items` debe ser una lista de DAG paths o componentes.",
                recoverable=True,
            )
        items = [_validate_dag_path(item, "selection.set") for item in raw_items]
        clear = bool(data.get("clear", False))
        if not clear and not items:
            raise ValidationError(
                code="EMPTY_SELECTION_REQUEST",
                message="Proporcione al menos un elemento en `items` o `clear=true`.",
                recoverable=True,
            )
        return cls(items=items, clear=clear)


@dataclass(frozen=True)
class ConfirmRolesRequest:
    """Entrada para `retopo.confirm_roles` (Fase 2)."""

    high_poly: str | None = None
    retopology: str | None = None
    use_current_selection: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ConfirmRolesRequest:
        data = raw or {}
        allowed = {"high_poly", "retopology", "use_current_selection"}
        _reject_unexpected_keys(data, allowed, "retopo.confirm_roles")

        use_sel = bool(data.get("use_current_selection", False))
        hp_raw = data.get("high_poly")
        rt_raw = data.get("retopology")

        hp = _validate_dag_path(hp_raw, "retopo.confirm_roles") if hp_raw else None
        rt = _validate_dag_path(rt_raw, "retopo.confirm_roles") if rt_raw else None

        if not use_sel and (not hp or not rt):
            raise ValidationError(
                code="MISSING_ROLE_DAG_PATHS",
                message=(
                    "`retopo.confirm_roles` requiere los DAG paths explícitos `high_poly` y `retopology`, "
                    "o bien `use_current_selection=true`."
                ),
                recoverable=True,
                suggestion="Especifique `high_poly` y `retopology` o seleccione ambas mallas en Maya y pase `use_current_selection=true`.",
            )
        if hp and rt and hp == rt:
            raise ValidationError(
                code="DUPLICATE_ROLE_MESH",
                message="`high_poly` y `retopology` deben ser mallas distintas.",
                recoverable=True,
            )

        return cls(high_poly=hp, retopology=rt, use_current_selection=use_sel)


@dataclass(frozen=True)
class DetectCandidatesRequest:
    """Entrada para `retopo.detect_candidates`."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> DetectCandidatesRequest:
        if raw:
            _reject_unexpected_keys(raw, set(), "retopo.detect_candidates")
        return cls()


@dataclass(frozen=True)
class AnalyzeMeshRequest:
    """Entrada para `retopo.analyze_mesh`."""

    dag_path: str
    coincident_tolerance: float = 1e-4

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AnalyzeMeshRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"dag_path", "coincident_tolerance"}, "retopo.analyze_mesh")
        dag = _validate_dag_path(data.get("dag_path"), "retopo.analyze_mesh")
        tol = float(data.get("coincident_tolerance", 1e-4))
        if tol <= 0 or tol > 10.0:
            raise ValidationError(
                code="INVALID_TOLERANCE",
                message="`coincident_tolerance` debe estar entre 1e-8 y 10.0.",
                recoverable=True,
            )
        return cls(dag_path=dag, coincident_tolerance=tol)


@dataclass(frozen=True)
class AnalyzeSymmetryRequest:
    """Entrada para `retopo.analyze_symmetry`."""

    dag_path: str
    tolerance: float = 0.05

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> AnalyzeSymmetryRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"dag_path", "tolerance"}, "retopo.analyze_symmetry")
        dag = _validate_dag_path(data.get("dag_path"), "retopo.analyze_symmetry")
        tol = float(data.get("tolerance", 0.05))
        if tol <= 0 or tol > 100.0:
            raise ValidationError(
                code="INVALID_TOLERANCE",
                message="`tolerance` debe ser mayor que 0 y menor o igual a 100.0.",
                recoverable=True,
            )
        return cls(dag_path=dag, tolerance=tol)


@dataclass(frozen=True)
class BoundaryLoopsRequest:
    """Entrada para `retopo.boundary_loops`."""

    dag_path: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BoundaryLoopsRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"dag_path"}, "retopo.boundary_loops")
        dag = _validate_dag_path(data.get("dag_path"), "retopo.boundary_loops")
        return cls(dag_path=dag)


@dataclass(frozen=True)
class ViewportCaptureRequest:
    """Entrada tipada para `viewport.capture` (Sección 6)."""

    camera: str = "persp"
    width: int = 1024
    height: int = 1024
    wireframe_on_shaded: bool = True
    isolate: list[str] = field(default_factory=list)
    frame_selected: bool = True
    file_name: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ViewportCaptureRequest:
        data = raw or {}
        allowed = {
            "camera",
            "width",
            "height",
            "wireframe_on_shaded",
            "isolate",
            "frame_selected",
            "file_name",
        }
        _reject_unexpected_keys(data, allowed, "viewport.capture")

        camera = str(data.get("camera", "persp")).strip()
        if not camera or any(ch in camera for ch in (";", "\n", "\r", "`", "$")):
            raise ValidationError(
                code="INVALID_CAMERA_NAME",
                message=f"Nombre de cámara inválido: '{camera}'.",
                recoverable=True,
                suggestion="Use una cámara válida como 'persp', 'front', 'side' o 'top'.",
            )

        width = int(data.get("width", 1024))
        height = int(data.get("height", 1024))
        if not (64 <= width <= 4096) or not (64 <= height <= 4096):
            raise ValidationError(
                code="INVALID_DIMENSIONS",
                message=f"Las dimensiones ({width}x{height}) deben estar entre 64x64 y 4096x4096.",
                recoverable=True,
            )

        raw_isolate = data.get("isolate") or []
        if not isinstance(raw_isolate, list):
            raise ValidationError(
                code="INVALID_ISOLATE_LIST",
                message="El parámetro `isolate` debe ser una lista de DAG paths.",
                recoverable=True,
            )
        isolate = [_validate_dag_path(item, "viewport.capture") for item in raw_isolate]

        file_name_raw = data.get("file_name")
        file_name: str | None = None
        if file_name_raw is not None:
            file_name = str(file_name_raw).strip()
            if "/" in file_name or "\\" in file_name or ".." in file_name:
                raise ValidationError(
                    code="INVALID_CAPTURE_FILENAME",
                    message="`file_name` debe ser un nombre de archivo simple sin separadores de directorio.",
                    recoverable=True,
                    suggestion="Use un nombre como 'vista_frontal.png'.",
                )

        return cls(
            camera=camera,
            width=width,
            height=height,
            wireframe_on_shaded=bool(data.get("wireframe_on_shaded", True)),
            isolate=isolate,
            frame_selected=bool(data.get("frame_selected", True)),
            file_name=file_name,
        )


@dataclass(frozen=True)
class SafetyCheckpointRequest:
    """Entrada tipada para `safety.checkpoint` (Fase 3)."""

    reason: str = "pre_operation_checkpoint"
    base_name: str = "checkpoint.mb"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SafetyCheckpointRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"reason", "base_name"}, "safety.checkpoint")
        reason = str(data.get("reason", "pre_operation_checkpoint")).strip()
        if not reason:
            raise ValidationError(
                code="EMPTY_CHECKPOINT_REASON",
                message="El parámetro `reason` no puede estar vacío.",
                recoverable=True,
            )
        base_name = str(data.get("base_name", "checkpoint.mb")).strip()
        if "/" in base_name or "\\" in base_name or ".." in base_name:
            raise ValidationError(
                code="INVALID_CHECKPOINT_NAME",
                message="`base_name` debe ser un nombre de archivo simple sin rutas.",
                recoverable=True,
            )
        return cls(reason=reason, base_name=base_name)


@dataclass(frozen=True)
class PreviewRegionRequest:
    """Entrada tipada para `retopo.preview_region` (Fase 3)."""

    operation_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    views: list[str] = field(default_factory=lambda: ["front", "side", "top"])

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> PreviewRegionRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"operation_id", "parameters", "views"}, "retopo.preview_region")
        op_id = str(data.get("operation_id") or "").strip()
        if not op_id:
            raise ValidationError(
                code="MISSING_OPERATION_ID",
                message="`retopo.preview_region` requiere `operation_id` (ej. 'hands_v1').",
                recoverable=True,
                suggestion="Use uno de los operation_id registrados: feet_v1, hands_v1, head_face_v1.",
            )
        params = data.get("parameters") or {}
        if not isinstance(params, dict):
            raise ValidationError(
                code="INVALID_OPERATION_PARAMETERS",
                message="El campo `parameters` debe ser un objeto JSON (dict).",
                recoverable=True,
            )
        raw_views = data.get("views")
        if raw_views is None:
            views = ["front", "side", "top"]
        else:
            if not isinstance(raw_views, list) or not raw_views:
                raise ValidationError(
                    code="INVALID_VIEWS_LIST",
                    message="`views` debe ser una lista no vacía de nombres de cámara.",
                    recoverable=True,
                )
            views = [str(v).strip() for v in raw_views if str(v).strip()]
        return cls(operation_id=op_id, parameters=dict(params), views=views)


@dataclass(frozen=True)
class RetopoValidateRequest:
    """Entrada tipada para `retopo.validate` (Fase 4)."""

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> RetopoValidateRequest:
        if raw:
            _reject_unexpected_keys(raw, set(), "retopo.validate")
        return cls()


@dataclass(frozen=True)
class SceneSaveVersionRequest:
    """Entrada tipada para `scene.save_version` (Fase 4)."""

    base_name: str | None = None
    target_path: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SceneSaveVersionRequest:
        data = raw or {}
        _reject_unexpected_keys(data, {"base_name", "target_path"}, "scene.save_version")
        base_name = str(data["base_name"]).strip() if data.get("base_name") else None
        target_path = str(data["target_path"]).strip() if data.get("target_path") else None
        return cls(base_name=base_name, target_path=target_path)


@dataclass(frozen=True)
class ApplyRegionRequest:
    """Entrada tipada para `retopo.apply_region` (Fase 4)."""

    operation_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    approved: bool = False
    base_name: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ApplyRegionRequest:
        data = raw or {}
        allowed = {"operation_id", "parameters", "approved", "base_name"}
        _reject_unexpected_keys(data, allowed, "retopo.apply_region")

        op_id = str(data.get("operation_id") or "").strip()
        if not op_id:
            raise ValidationError(
                code="MISSING_OPERATION_ID",
                message="`retopo.apply_region` requiere `operation_id`.",
                recoverable=True,
            )

        params = data.get("parameters") or {}
        if not isinstance(params, dict):
            raise ValidationError(
                code="INVALID_OPERATION_PARAMETERS",
                message="El campo `parameters` debe ser un objeto JSON.",
                recoverable=True,
            )

        approved = bool(data.get("approved", False))
        if not approved:
            raise ValidationError(
                code="EXPLICIT_APPROVAL_REQUIRED",
                message="`retopo.apply_region` requiere aprobación explícita (`approved: true`).",
                recoverable=True,
                suggestion="Ejecute primero `retopo.preview_region` y confirme con `approved: true`.",
            )

        base_name = str(data["base_name"]).strip() if data.get("base_name") else None
        return cls(
            operation_id=op_id,
            parameters=dict(params),
            approved=approved,
            base_name=base_name,
        )
