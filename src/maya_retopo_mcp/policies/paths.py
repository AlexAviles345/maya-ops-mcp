"""Políticas de aislamiento de rutas, rechazo de `original/` y versionado seguro (Sección 5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePath

from maya_retopo_mcp.errors import SecurityPolicyError

FORBIDDEN_SHELL_CHARS: frozenset[str] = frozenset({";", "|", "&", "`", "$", ">", "<", "\n", "\r", "\x00"})
VERSION_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)_v(?P<num>\d{3,})(?P<ext>\.(?:ma|mb|json))$", re.IGNORECASE)


def _reject_unsafe_raw_path(raw_path: str) -> None:
    """Rechaza traversal explícito (`..`), rutas UNC, rutas relativas o caracteres de shell."""
    if not raw_path or not raw_path.strip():
        raise SecurityPolicyError(
            code="EMPTY_PATH",
            message="La ruta proporcionada está vacía.",
            recoverable=True,
            suggestion="Proporcione una ruta absoluta válida dentro del proyecto.",
        )

    cleaned = raw_path.strip()

    if any(ch in cleaned for ch in FORBIDDEN_SHELL_CHARS):
        raise SecurityPolicyError(
            code="SHELL_PATH_FORBIDDEN",
            message="La ruta contiene caracteres de shell o control no permitidos.",
            recoverable=False,
            suggestion="Proporcione una ruta de sistema de archivos literal sin caracteres especiales.",
        )

    if cleaned.startswith("\\\\") or cleaned.startswith("//"):
        raise SecurityPolicyError(
            code="UNC_PATH_FORBIDDEN",
            message="Las rutas UNC o de red están prohibidas en el MVP.",
            recoverable=False,
            suggestion="Use una ruta local absoluta (por ejemplo C:/proyecto/...).",
        )

    normalized_slashes = cleaned.replace("\\", "/")
    parts = [p for p in normalized_slashes.split("/") if p]
    if ".." in parts or "." in parts:
        raise SecurityPolicyError(
            code="PATH_TRAVERSAL_FORBIDDEN",
            message="No se permiten segmentos '.' o '..' en las rutas.",
            recoverable=False,
            suggestion="Proporcione una ruta canónica absoluta sin '..'.",
        )

    pure = PurePath(cleaned)
    if not pure.is_absolute():
        raise SecurityPolicyError(
            code="RELATIVE_PATH_FORBIDDEN",
            message=f"La ruta '{raw_path}' debe ser absoluta.",
            recoverable=True,
            suggestion="Especifique la ruta absoluta completa incluyendo la unidad.",
        )


def resolve_safe_path(raw_path: str) -> Path:
    """Valida sintácticamente y resuelve una ruta absoluta sin permitir traversal ni UNC."""
    _reject_unsafe_raw_path(raw_path)
    resolved = Path(raw_path).resolve()
    if str(resolved).startswith("\\\\"):
        raise SecurityPolicyError(
            code="UNC_PATH_FORBIDDEN",
            message="La ruta resuelta apunta a un recurso de red UNC no permitido.",
            recoverable=False,
            suggestion="Use almacenamiento local en el equipo host.",
        )
    return resolved


@dataclass(frozen=True)
class ProjectPathsPolicy:
    """Política activa de carpetas permitidas para un proyecto conectado."""

    project_root: Path
    original_dir: Path
    output_dir: Path
    reports_dir: Path
    backups_dir: Path

    @classmethod
    def from_raw(
        cls,
        *,
        project_root: str,
        original_dir: str,
        output_dir: str,
        reports_dir: str,
        backups_dir: str,
    ) -> ProjectPathsPolicy:
        root = resolve_safe_path(project_root)
        orig = resolve_safe_path(original_dir)
        out = resolve_safe_path(output_dir)
        rep = resolve_safe_path(reports_dir)
        bak = resolve_safe_path(backups_dir)

        for label, sub in (
            ("original_dir", orig),
            ("output_dir", out),
            ("reports_dir", rep),
            ("backups_dir", bak),
        ):
            if sub == root or not sub.is_relative_to(root):
                raise SecurityPolicyError(
                    code="OUTSIDE_PROJECT_ROOT",
                    message=f"El directorio '{label}' ({sub}) debe estar dentro de project_root ({root}).",
                    recoverable=True,
                    suggestion="Configure todas las subcarpetas dentro de project_root.",
                )

        # Verificar que original_dir no se solape con carpetas de escritura
        for write_label, write_dir in (
            ("output_dir", out),
            ("reports_dir", rep),
            ("backups_dir", bak),
        ):
            if write_dir == orig or write_dir.is_relative_to(orig) or orig.is_relative_to(write_dir):
                raise SecurityPolicyError(
                    code="ORIGINAL_DIR_OVERLAP",
                    message=f"'{write_label}' no puede coincidir ni solaparse con 'original_dir'.",
                    recoverable=True,
                    suggestion="Use carpetas separadas para original, output, reports y backups.",
                )

        return cls(
            project_root=root,
            original_dir=orig,
            output_dir=out,
            reports_dir=rep,
            backups_dir=bak,
        )

    def ensure_not_in_original(self, target: Path) -> None:
        """Lanza error si el archivo objetivo reside en `original_dir`."""
        if target == self.original_dir or target.is_relative_to(self.original_dir):
            raise SecurityPolicyError(
                code="ORIGINAL_DIR_READ_ONLY",
                message="Operación rechazada: la carpeta 'original/' es estrictamente de solo lectura.",
                recoverable=True,
                suggestion="Guarde versiones nuevas únicamente en 'output/' o checkpoints en 'backups/'.",
            )

    def validate_write_target(
        self,
        raw_target_path: str,
        *,
        category: str,
        allow_overwrite: bool = False,
    ) -> Path:
        """
        Valida que un archivo de salida se escriba exclusivamente en la carpeta autorizada
        (`output`, `reports` o `backups`) y nunca sobrescriba archivos cuando no está permitido.
        """
        target = resolve_safe_path(raw_target_path)
        self.ensure_not_in_original(target)

        if not target.is_relative_to(self.project_root):
            raise SecurityPolicyError(
                code="OUTSIDE_PROJECT_ROOT",
                message=f"El destino '{target}' está fuera de project_root.",
                recoverable=True,
                suggestion="Escriba únicamente dentro de las carpetas declaradas del proyecto.",
            )

        allowed_parent = {
            "output": self.output_dir,
            "reports": self.reports_dir,
            "backups": self.backups_dir,
        }.get(category)

        if allowed_parent is None:
            raise SecurityPolicyError(
                code="INVALID_WRITE_CATEGORY",
                message=f"Categoría de escritura desconocida: '{category}'.",
                recoverable=False,
                suggestion="Use una de las categorías válidas: output, reports, backups.",
            )

        if target == allowed_parent or not target.is_relative_to(allowed_parent):
            raise SecurityPolicyError(
                code="UNAUTHORIZED_DIRECTORY",
                message=f"El archivo para '{category}' debe ubicarse dentro de '{allowed_parent}'.",
                recoverable=True,
                suggestion=f"Cambie la ruta de destino a una ubicación dentro de '{allowed_parent}'.",
            )

        if not allow_overwrite and target.exists():
            raise SecurityPolicyError(
                code="FILE_ALREADY_EXISTS",
                message=f"No se permite sobrescribir el archivo existente: '{target.name}'.",
                recoverable=True,
                suggestion="Incremente el número de versión para crear un archivo nuevo.",
            )

        return target

    def next_version_path(self, base_name_or_path: str, *, directory_category: str = "output") -> Path:
        """
        Calcula la siguiente ruta versionada disponible (ej. `personaje_v001.mb` -> `personaje_v002.mb`)
        garantizando que nunca exista previamente en disco.
        """
        target_dir = {
            "output": self.output_dir,
            "reports": self.reports_dir,
            "backups": self.backups_dir,
        }.get(directory_category)

        if target_dir is None:
            raise SecurityPolicyError(
                code="INVALID_WRITE_CATEGORY",
                message=f"Categoría inválida para versionado: '{directory_category}'.",
                recoverable=False,
            )

        file_name = Path(base_name_or_path).name
        match = VERSION_SUFFIX_RE.match(file_name)
        if match:
            stem = match.group("stem")
            version_num = int(match.group("num")) + 1
            ext = match.group("ext")
        else:
            path_obj = Path(file_name)
            stem = path_obj.stem or "scene"
            ext = path_obj.suffix if path_obj.suffix.lower() in {".ma", ".mb", ".json"} else ".mb"
            version_num = 1

        while True:
            candidate = target_dir / f"{stem}_v{version_num:03d}{ext}"
            if not candidate.exists():
                return self.validate_write_target(
                    str(candidate),
                    category=directory_category,
                    allow_overwrite=False,
                )
            version_num += 1

