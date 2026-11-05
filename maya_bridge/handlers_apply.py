"""Handlers de auditoría (`retopo.validate`) y aplicación/guardado (`retopo.apply_region`, `scene.save_version`)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from maya_bridge.checkpoint import create_scene_checkpoint
from maya_bridge.handlers_preview import (
    BridgeActionError,
    _replace_simulated_mesh,
    maya_undo_chunk,
)
from maya_bridge.handlers_read import (
    _find_mesh_snapshot,
    _get_maya_cmds,
    get_current_scene_state,
    get_simulated_state,
)
from maya_bridge.topology import (
    MeshGeometrySnapshot,
    analyze_mesh_topology,
    compute_snapshot_fingerprint,
)
from operations import dispatch_registered_operation


def evaluate_full_retopo_audit(
    *,
    hp_snap: MeshGeometrySnapshot,
    rt_snap: MeshGeometrySnapshot,
    expected_hp_hash: str,
) -> dict[str, Any]:
    """
    Ejecuta todas las comprobaciones individuales de auditoría sin ocultar errores parciales
    (Sección 6: `retopo.validate` y Sección 11: Criterios de aceptación).
    """
    hp_fp = compute_snapshot_fingerprint(hp_snap)
    rt_fp = compute_snapshot_fingerprint(rt_snap)
    topo = analyze_mesh_topology(rt_snap)

    hp_ok = (not expected_hp_hash) or (hp_fp["structural_hash"] == expected_hp_hash)
    ft = topo["face_types"]
    nm = topo["non_manifold"]
    deg = topo["degeneracies"]
    norm = topo["normals"]

    checks: list[dict[str, Any]] = [
        {
            "check_id": "high_poly_unchanged",
            "passed": hp_ok,
            "details": {
                "expected_hash": expected_hp_hash or hp_fp["structural_hash"],
                "actual_hash": hp_fp["structural_hash"],
            },
        },
        {
            "check_id": "quads_only",
            "passed": bool(topo["is_all_quads"]),
            "details": {
                "quads": ft["quads"],
                "triangles": ft["triangles"],
                "ngons": ft["ngons"],
                "invalid_faces": ft["invalid_faces"],
                "quad_percentage": ft["quad_percentage"],
            },
        },
        {
            "check_id": "no_non_manifold",
            "passed": nm["edges_count"] == 0 and nm["vertices_count"] == 0,
            "details": {
                "non_manifold_edges": nm["edges_count"],
                "non_manifold_vertices": nm["vertices_count"],
            },
        },
        {
            "check_id": "no_lamina_faces",
            "passed": deg["lamina_faces_count"] == 0,
            "details": {"lamina_faces_count": deg["lamina_faces_count"]},
        },
        {
            "check_id": "no_zero_length_edges",
            "passed": deg["zero_length_edges_count"] == 0,
            "details": {"zero_length_edges_count": deg["zero_length_edges_count"]},
        },
        {
            "check_id": "no_zero_area_faces",
            "passed": deg["zero_area_faces_count"] == 0,
            "details": {"zero_area_faces_count": deg["zero_area_faces_count"]},
        },
        {
            "check_id": "no_coincident_vertices",
            "passed": deg["coincident_vertex_groups_count"] == 0,
            "details": {
                "coincident_vertex_groups_count": deg["coincident_vertex_groups_count"],
                "coincident_vertex_count": deg["coincident_vertex_count"],
            },
        },
        {
            "check_id": "consistent_normals",
            "passed": bool(norm["consistent"]),
            "details": {
                "inconsistent_winding_edges_count": norm["inconsistent_winding_edges_count"],
            },
        },
    ]

    failed_checks = [c["check_id"] for c in checks if not c["passed"]]
    overall_passed = len(failed_checks) == 0

    return {
        "passed": overall_passed,
        "failed_checks": failed_checks,
        "checks": checks,
        "high_poly_fingerprint": hp_fp,
        "retopology_fingerprint": rt_fp,
        "topology": topo,
    }


def _save_scene_file(target_path: Path, audit_summary: dict[str, Any]) -> None:
    """Guarda la escena actual en `target_path` sin sobrescribir archivos existentes."""
    if target_path.exists():
        raise BridgeActionError(
            "FILE_ALREADY_EXISTS",
            f"No se permite sobrescribir el archivo existente: '{target_path}'.",
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    cmds = _get_maya_cmds()
    if cmds is not None:
        file_type = "mayaAscii" if target_path.suffix.lower() == ".ma" else "mayaBinary"
        cmds.file(rename=str(target_path))
        cmds.file(save=True, type=file_type)
        cmds.file(modified=False)
    else:
        sim = get_simulated_state()
        meshes: list[MeshGeometrySnapshot] = list(sim.get("meshes", []))
        serialized_meshes = [
            {
                "transform_dag_path": m.transform_dag_path,
                "shape_dag_path": m.shape_dag_path,
                "uuid": m.uuid,
                "vertices": [list(pt) for pt in m.vertices],
                "faces": [list(f) for f in m.faces],
                "visible": m.visible,
                "intermediate_object": m.intermediate_object,
            }
            for m in meshes
        ]
        payload = {
            "scene_format": "maya_retopo_mcp_scene_v1",
            "saved_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "scene_path": target_path.as_posix(),
            "meshes": serialized_meshes,
            "audit_passed": audit_summary["passed"],
        }
        target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        sim["scene"] = target_path.as_posix()
        sim["modified"] = False


def _reopen_scene_file(target_path: Path) -> None:
    """Reabre la escena recién guardada desde disco para validación independiente."""
    if not target_path.exists():
        raise BridgeActionError(
            "SAVED_SCENE_MISSING",
            f"No se encontró el archivo guardado para reapertura: '{target_path}'.",
        )
    cmds = _get_maya_cmds()
    if cmds is not None:
        cmds.file(str(target_path), open=True, force=True)
    else:
        raw = json.loads(target_path.read_text(encoding="utf-8"))
        loaded_meshes: list[MeshGeometrySnapshot] = []
        for item in raw.get("meshes", []):
            loaded_meshes.append(
                MeshGeometrySnapshot(
                    transform_dag_path=str(item["transform_dag_path"]),
                    shape_dag_path=str(item["shape_dag_path"]),
                    uuid=str(item["uuid"]),
                    vertices=[(float(p[0]), float(p[1]), float(p[2])) for p in item["vertices"]],
                    faces=[tuple(int(idx) for idx in f) for f in item["faces"]],
                    visible=bool(item.get("visible", True)),
                    intermediate_object=bool(item.get("intermediate_object", False)),
                )
            )
        sim = get_simulated_state()
        sim["meshes"] = loaded_meshes
        sim["scene"] = target_path.as_posix()
        sim["modified"] = False


def handle_retopo_validate(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `retopo.validate` (Sección 6).
    Ejecuta la auditoría final sin modificar la escena y devuelve `passed` junto a cada comprobación.
    """
    high_poly_dag = str(params.get("high_poly_dag") or "").strip()
    retopology_dag = str(params.get("retopology_dag") or "").strip()
    expected_hp_hash = str(params.get("expected_high_poly_hash") or "").strip()

    hp_snap = _find_mesh_snapshot(high_poly_dag)
    rt_snap = _find_mesh_snapshot(retopology_dag)
    return evaluate_full_retopo_audit(
        hp_snap=hp_snap,
        rt_snap=rt_snap,
        expected_hp_hash=expected_hp_hash,
    )


def handle_scene_save_version(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `scene.save_version` (Sección 6).
    Guarda una copia nueva con incremento de versión rechazando cambios en high-poly o fallos de validación.
    """
    output_path_str = str(params.get("output_path") or "").strip()
    high_poly_dag = str(params.get("high_poly_dag") or "").strip()
    retopology_dag = str(params.get("retopology_dag") or "").strip()
    expected_hp_hash = str(params.get("expected_high_poly_hash") or "").strip()

    if not output_path_str:
        raise BridgeActionError("MISSING_OUTPUT_PATH", "Se requiere `output_path`.")

    hp_snap = _find_mesh_snapshot(high_poly_dag)
    rt_snap = _find_mesh_snapshot(retopology_dag)
    audit = evaluate_full_retopo_audit(
        hp_snap=hp_snap,
        rt_snap=rt_snap,
        expected_hp_hash=expected_hp_hash,
    )

    if "high_poly_unchanged" in audit["failed_checks"]:
        raise BridgeActionError(
            "HIGH_POLY_CHANGED",
            "La escultura protegida cambio; se rechaza el guardado de versión.",
        )

    if not audit["passed"]:
        raise BridgeActionError(
            "VALIDATION_FAILED",
            (
                "No se puede guardar la versión porque la validación topológica falló en: "
                f"{', '.join(audit['failed_checks'])}."
            ),
        )

    previous_scene, _ = get_current_scene_state()
    target_path = Path(output_path_str)
    _save_scene_file(target_path, audit)

    return {
        "saved": True,
        "previous_scene": previous_scene,
        "saved_scene": target_path.as_posix(),
        "validation_passed": True,
        "high_poly_fingerprint": audit["high_poly_fingerprint"],
        "retopology_fingerprint": audit["retopology_fingerprint"],
    }


def handle_retopo_apply_region(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `retopo.apply_region` (Sección 6):
    1. Comprueba huella inicial de high-poly.
    2. Crea checkpoint en `backups/`.
    3. Ejecuta operación regional dentro de un undo chunk (`always_undo=False`, revierte si hay error).
    4. Valida topología y huella high-poly.
    5. Guarda una versión nueva en `output/`.
    6. Reabre esa versión y repite validación de solo lectura.
    7. Si falla, conserva la escena anterior y marca la nueva como rechazada.
    """
    operation_id = str(params.get("operation_id") or "").strip()
    op_params = dict(params.get("parameters") or {})
    checkpoint_path_str = str(params.get("checkpoint_path") or "").strip()
    output_path_str = str(params.get("output_path") or "").strip()
    high_poly_dag = str(params.get("high_poly_dag") or "").strip()
    retopology_dag = str(params.get("retopology_dag") or "").strip()
    expected_hp_hash = str(params.get("expected_high_poly_hash") or "").strip()

    previous_scene, _ = get_current_scene_state()

    hp_before_snap = _find_mesh_snapshot(high_poly_dag)
    hp_before_fp = compute_snapshot_fingerprint(hp_before_snap)
    if expected_hp_hash and hp_before_fp["structural_hash"] != expected_hp_hash:
        raise BridgeActionError(
            "HIGH_POLY_CHANGED",
            "La escultura protegida cambio antes de aplicar la región.",
        )

    # Paso 2: Crear checkpoint recuperable antes de mutar
    checkpoint_info = create_scene_checkpoint(
        checkpoint_path=checkpoint_path_str,
        reason=f"pre_apply_{operation_id}",
        high_poly_dag=high_poly_dag,
        retopology_dag=retopology_dag,
    )

    output_path = Path(output_path_str)

    # Paso 3..7 dentro de undo chunk con rollback automático ante error
    with maya_undo_chunk(f"apply_{operation_id}", always_undo=False):
        rt_before_snap = _find_mesh_snapshot(retopology_dag)
        updated_rt_snap, op_summary = dispatch_registered_operation(
            operation_id,
            rt_before_snap,
            op_params,
        )
        _replace_simulated_mesh(updated_rt_snap)

        # Paso 4: Validar antes de guardar
        hp_after_snap = _find_mesh_snapshot(high_poly_dag)
        pre_save_audit = evaluate_full_retopo_audit(
            hp_snap=hp_after_snap,
            rt_snap=updated_rt_snap,
            expected_hp_hash=hp_before_fp["structural_hash"],
        )

        if "high_poly_unchanged" in pre_save_audit["failed_checks"]:
            raise BridgeActionError(
                "HIGH_POLY_CHANGED",
                "La escultura protegida cambio durante la aplicación de la región.",
            )

        if not pre_save_audit["passed"]:
            raise BridgeActionError(
                "APPLY_VALIDATION_FAILED",
                (
                    f"La región '{operation_id}' no superó la validación previa al guardado: "
                    f"{', '.join(pre_save_audit['failed_checks'])}."
                ),
            )

        # Paso 5: Guardar nueva versión en output/
        _save_scene_file(output_path, pre_save_audit)

        # Paso 6: Reabrir esa versión y repetir validación de solo lectura
        try:
            _reopen_scene_file(output_path)
            reopened_hp = _find_mesh_snapshot(high_poly_dag)
            reopened_rt = _find_mesh_snapshot(retopology_dag)
            reopened_audit = evaluate_full_retopo_audit(
                hp_snap=reopened_hp,
                rt_snap=reopened_rt,
                expected_hp_hash=hp_before_fp["structural_hash"],
            )
            if not reopened_audit["passed"]:
                raise BridgeActionError(
                    "REOPEN_VALIDATION_FAILED",
                    (
                        "La versión guardada falló al reabrir y revalidar: "
                        f"{', '.join(reopened_audit['failed_checks'])}."
                    ),
                )
        except Exception:
            # Paso 7: Si falla al reabrir/revalidar, marcar la nueva versión como rechazada y restaurar escena previa
            if output_path.exists():
                rejected_path = output_path.with_suffix(output_path.suffix + ".rejected")
                output_path.replace(rejected_path)
            if previous_scene:
                get_simulated_state()["scene"] = previous_scene
            raise

    return {
        "applied": True,
        "operation_id": operation_id,
        "parameters": op_params,
        "operation_summary": op_summary,
        "checkpoint": checkpoint_info,
        "previous_scene": previous_scene,
        "saved_scene": output_path.as_posix(),
        "reopened_and_revalidated": True,
        "validation": reopened_audit,
    }
