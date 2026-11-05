"""Creación de checkpoints recuperables sin sobrescritura en `backups_dir` (Fase 3)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maya_bridge.handlers_read import (
    _find_mesh_snapshot,
    _get_maya_cmds,
    get_current_scene_state,
)
from maya_bridge.topology import compute_snapshot_fingerprint


def create_scene_checkpoint(
    *,
    checkpoint_path: str,
    reason: str,
    high_poly_dag: str | None = None,
    retopology_dag: str | None = None,
) -> dict[str, Any]:
    """
    Crea una copia recuperable de la escena en `checkpoint_path` (dentro de `backups_dir`),
    sin sobrescribir archivos existentes ni alterar el nombre de escena activa de la sesión.
    """
    target = Path(checkpoint_path)
    if target.exists():
        raise FileExistsError(f"El archivo de checkpoint ya existe y no puede sobrescribirse: '{target}'.")

    target.parent.mkdir(parents=True, exist_ok=True)
    source_scene, prev_modified = get_current_scene_state()
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    hp_fp: dict[str, Any] | None = None
    rt_fp: dict[str, Any] | None = None
    if high_poly_dag:
        hp_fp = compute_snapshot_fingerprint(_find_mesh_snapshot(high_poly_dag))
    if retopology_dag:
        rt_fp = compute_snapshot_fingerprint(_find_mesh_snapshot(retopology_dag))

    cmds = _get_maya_cmds()
    if cmds is not None:
        file_type = "mayaAscii" if target.suffix.lower() == ".ma" else "mayaBinary"
        orig_name = cmds.file(query=True, sceneName=True)
        try:
            cmds.file(rename=str(target))
            cmds.file(save=True, type=file_type)
        finally:
            if orig_name:
                cmds.file(rename=orig_name)
            cmds.file(modified=prev_modified)
    else:
        payload = {
            "checkpoint_format": "maya_retopo_mcp_checkpoint_v1",
            "timestamp": timestamp,
            "source_scene": source_scene,
            "reason": reason,
            "high_poly_fingerprint": hp_fp,
            "retopology_fingerprint": rt_fp,
        }
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "checkpoint_path": target.as_posix(),
        "timestamp": timestamp,
        "source_scene": source_scene,
        "reason": reason,
        "high_poly_fingerprint": hp_fp,
        "retopology_fingerprint": rt_fp,
    }
