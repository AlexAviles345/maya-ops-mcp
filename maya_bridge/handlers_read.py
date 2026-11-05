"""Handlers de solo lectura ejecutados dentro de Maya (Fase 0 y Fase 1)."""

from __future__ import annotations

import sys
from typing import Any


def _get_maya_cmds() -> Any | None:
    """Importa `maya.cmds` únicamente cuando el puente corre dentro de Maya."""
    try:
        import maya.cmds as cmds  # type: ignore[import-not-found]

        return cmds
    except ImportError:
        return None


def get_current_scene_state() -> tuple[str | None, bool]:
    """Devuelve `(scene_path, modified)` sin alterar el estado de la escena."""
    cmds = _get_maya_cmds()
    if cmds is None:
        return (None, False)
    try:
        scene_name = cmds.file(query=True, sceneName=True) or None
        modified = bool(cmds.file(query=True, modified=True))
        return (scene_name, modified)
    except Exception:
        return (None, False)


def handle_maya_health(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `maya.health` dentro del puente de Maya.
    No modifica la escena ni ensucia el flag `modified`.
    """
    _ = params
    cmds = _get_maya_cmds()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    if cmds is not None:
        maya_version = str(cmds.about(version=True))
        scene_name, modified = get_current_scene_state()
    else:
        maya_version = "2027"
        scene_name = None
        modified = False

    return {
        "ok": True,
        "maya_version": maya_version,
        "python_version": py_ver,
        "scene": scene_name,
        "modified": modified,
    }

