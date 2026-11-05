"""Handlers de modo `PREVIEW` (Fase 2: selección/roles; Fase 3: checkpoint y preview regional con undo)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from maya_bridge.checkpoint import create_scene_checkpoint
from maya_bridge.handlers_read import (
    _extract_scene_meshes,
    _find_mesh_snapshot,
    _get_maya_cmds,
    get_simulated_state,
    handle_selection_get,
)
from maya_bridge.topology import (
    MeshGeometrySnapshot,
    analyze_mesh_topology,
    compute_snapshot_fingerprint,
)
from maya_bridge.viewport import capture_viewport_with_restore
from operations import dispatch_registered_operation


class BridgeActionError(RuntimeError):
    """Error tipado dentro del puente de Maya con código estructurado."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@contextmanager
def maya_undo_chunk(chunk_name: str, *, always_undo: bool = True) -> Iterator[None]:
    """
    Ejecuta un bloque dentro de un undo chunk de Maya (y de la escena simulada).
    Si `always_undo=True` (modo PREVIEW) o si ocurre una excepción, revierte automáticamente.
    """
    cmds = _get_maya_cmds()
    sim = get_simulated_state()
    sim_meshes_backup = list(sim.get("meshes", []))
    sim_modified_backup = bool(sim.get("modified", False))
    failed = False

    if cmds is not None:
        cmds.undoInfo(openChunk=True, chunkName=chunk_name)
    try:
        yield
    except Exception:
        failed = True
        raise
    finally:
        if cmds is not None:
            cmds.undoInfo(closeChunk=True)
            if always_undo or failed:
                try:
                    cmds.undo()
                except Exception:
                    pass
        if always_undo or failed:
            sim["meshes"] = sim_meshes_backup
            sim["modified"] = sim_modified_backup


def execute_with_rollback_on_error(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Ejecuta `fn` dentro de un undo chunk que hace undo automático si ocurre un error."""
    with maya_undo_chunk("maya_retopo_mcp_op", always_undo=False):
        return fn(*args, **kwargs)


def _replace_simulated_mesh(updated: MeshGeometrySnapshot) -> None:
    """Reemplaza en memoria la malla actualizada dentro del estado simulado."""
    sim = get_simulated_state()
    meshes: list[MeshGeometrySnapshot] = list(sim.get("meshes", []))
    for idx, m in enumerate(meshes):
        if m.transform_dag_path == updated.transform_dag_path:
            meshes[idx] = updated
            break
    sim["meshes"] = meshes


def _verify_selection_item_exists(item: str) -> None:
    """Verifica que el objeto o nodo base del componente exista en la escena."""
    cmds = _get_maya_cmds()
    base_node = item.split(".", 1)[0].strip()
    if cmds is not None:
        if not cmds.objExists(item):
            raise BridgeActionError(
                "NODE_NOT_FOUND",
                f"El objeto o componente '{item}' no existe en la escena de Maya.",
            )
        return

    meshes = _extract_scene_meshes()
    known_nodes = {"|persp", "|top", "|front", "|side"}
    for m in meshes:
        known_nodes.add(m.transform_dag_path)
        known_nodes.add(m.shape_dag_path)

    if base_node not in known_nodes:
        raise BridgeActionError(
            "NODE_NOT_FOUND",
            f"El nodo '{base_node}' (de '{item}') no existe en la escena actual.",
        )


def handle_selection_set(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `selection.set` (Sección 6).
    Selecciona objetos o componentes existentes sin modificar geometría ni alterar `modified`.
    """
    items = [str(x).strip() for x in (params.get("items") or []) if str(x).strip()]
    clear = bool(params.get("clear", False))

    if not clear and not items:
        raise BridgeActionError(
            "EMPTY_SELECTION_REQUEST",
            "Debe proporcionar al menos un elemento en `items` o especificar `clear=True`.",
        )

    for item in items:
        _verify_selection_item_exists(item)

    cmds = _get_maya_cmds()
    if cmds is not None:
        prev_mod = bool(cmds.file(query=True, modified=True))
        if clear and not items:
            cmds.select(clear=True)
        else:
            cmds.select(items, replace=True)
        cmds.file(modified=prev_mod)
    else:
        sim = get_simulated_state()
        sim["selection"] = [] if (clear and not items) else list(items)

    return handle_selection_get({"max_components": int(params.get("max_components", 500))})


def handle_retopo_confirm_roles(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `retopo.confirm_roles` (Sección 6).
    Confirma `high_poly` y `retopology` mediante DAG paths explícitos o selección actual del artista.
    """
    high_poly_arg = str(params.get("high_poly") or "").strip()
    retopo_arg = str(params.get("retopology") or "").strip()
    use_selection = bool(params.get("use_current_selection", False))

    if use_selection and (not high_poly_arg or not retopo_arg):
        sel_info = handle_selection_get({"max_components": 50})
        selected_objects = sel_info.get("objects") or []
        if len(selected_objects) < 2:
            raise BridgeActionError(
                "INSUFFICIENT_SELECTION_FOR_ROLES",
                (
                    "Para confirmar roles desde la selección (`use_current_selection=True`), "
                    "el artista debe seleccionar exactamente dos mallas en orden: [high_poly, retopology]."
                ),
            )
        high_poly_arg = str(selected_objects[0])
        retopo_arg = str(selected_objects[1])

    if not high_poly_arg or not retopo_arg:
        raise BridgeActionError(
            "MISSING_ROLE_DAG_PATHS",
            "Se requieren los DAG paths de `high_poly` y `retopology` (o `use_current_selection=True`).",
        )

    try:
        hp_snap = _find_mesh_snapshot(high_poly_arg)
    except ValueError as exc:
        raise BridgeActionError("HIGH_POLY_NOT_FOUND", str(exc)) from exc

    try:
        rt_snap = _find_mesh_snapshot(retopo_arg)
    except ValueError as exc:
        raise BridgeActionError("RETOPOLOGY_MESH_NOT_FOUND", str(exc)) from exc

    if hp_snap.transform_dag_path == rt_snap.transform_dag_path:
        raise BridgeActionError(
            "DUPLICATE_ROLE_MESH",
            f"`high_poly` y `retopology` no pueden apuntar a la misma malla ('{hp_snap.transform_dag_path}').",
        )

    hp_fp = compute_snapshot_fingerprint(hp_snap)
    rt_fp = compute_snapshot_fingerprint(rt_snap)

    confirmation = {
        "roles_confirmed": True,
        "confirmed_via": "artist_selection" if use_selection else "explicit_dag_paths",
        "high_poly": hp_fp,
        "retopology": rt_fp,
    }

    sim = get_simulated_state()
    sim["confirmed_roles"] = confirmation
    return confirmation


def handle_safety_checkpoint(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `safety.checkpoint` (Sección 6)."""
    checkpoint_path = str(params.get("checkpoint_path") or "").strip()
    reason = str(params.get("reason") or "manual_checkpoint").strip()
    high_poly_dag = params.get("high_poly_dag")
    retopology_dag = params.get("retopology_dag")

    if not checkpoint_path:
        raise BridgeActionError("MISSING_CHECKPOINT_PATH", "Se requiere `checkpoint_path`.")

    return create_scene_checkpoint(
        checkpoint_path=checkpoint_path,
        reason=reason,
        high_poly_dag=str(high_poly_dag) if high_poly_dag else None,
        retopology_dag=str(retopology_dag) if retopology_dag else None,
    )


def handle_retopo_preview_region(params: dict[str, Any]) -> dict[str, Any]:
    """
    Handler de `retopo.preview_region` (Sección 6):
    1. Valida escena y roles.
    2. Comprueba huella high-poly inicial.
    3. Registra topología inicial de retopología.
    4. Ejecuta el handler regional dentro de un undo chunk (`always_undo=True`).
    5. Valida que high-poly no cambió y audita la topología resultante.
    6. Captura vistas de comprobación.
    7. Ejecuta undo completo.
    8. Confirma que la escena regresó exactamente al estado inicial (`scene_restored: true`).
    """
    operation_id = str(params.get("operation_id") or "").strip()
    op_params = dict(params.get("parameters") or {})
    views = [str(v) for v in (params.get("views") or ["front", "side", "top"])]
    view_output_paths = dict(params.get("view_output_paths") or {})

    high_poly_dag = str(params.get("high_poly_dag") or "").strip()
    retopology_dag = str(params.get("retopology_dag") or "").strip()
    expected_hp_hash = str(params.get("expected_high_poly_hash") or "").strip()

    hp_before_snap = _find_mesh_snapshot(high_poly_dag)
    rt_before_snap = _find_mesh_snapshot(retopology_dag)

    hp_before_fp = compute_snapshot_fingerprint(hp_before_snap)
    if expected_hp_hash and hp_before_fp["structural_hash"] != expected_hp_hash:
        raise BridgeActionError(
            "HIGH_POLY_CHANGED",
            "La huella estructural de la escultura high-poly ya no coincide con la confirmada.",
        )

    rt_before_fp = compute_snapshot_fingerprint(rt_before_snap)
    topology_before = analyze_mesh_topology(rt_before_snap)

    op_summary: dict[str, Any] = {}
    topology_after: dict[str, Any] = {}
    captured_views: list[dict[str, Any]] = []

    with maya_undo_chunk(f"preview_{operation_id}", always_undo=True):
        updated_rt_snap, op_summary = dispatch_registered_operation(
            operation_id,
            rt_before_snap,
            op_params,
        )
        _replace_simulated_mesh(updated_rt_snap)

        # Verificar que la high-poly no fue alterada durante el handler regional
        hp_during_snap = _find_mesh_snapshot(high_poly_dag)
        hp_during_fp = compute_snapshot_fingerprint(hp_during_snap)
        if hp_during_fp["structural_hash"] != hp_before_fp["structural_hash"]:
            raise BridgeActionError(
                "HIGH_POLY_CHANGED",
                "La escultura protegida cambio durante la operacion.",
            )

        topology_after = analyze_mesh_topology(updated_rt_snap)
        if not topology_after["is_all_quads"] or not topology_after["is_clean_topology"]:
            raise BridgeActionError(
                "PREVIEW_TOPOLOGY_INVALID",
                "La operación regional produjo topología inválida (no-quads, non-manifold o degeneraciones).",
            )

        cmds = _get_maya_cmds()
        sim_vp = get_simulated_state().get("viewport")
        for view_cam in views:
            out_file = view_output_paths.get(view_cam)
            cap = capture_viewport_with_restore(
                cmds=cmds,
                camera=view_cam,
                width=512,
                height=512,
                wireframe_on_shaded=True,
                isolate=[high_poly_dag, retopology_dag],
                frame_selected=True,
                output_path=str(out_file) if out_file else None,
                simulated_state=sim_vp,
            )
            captured_views.append(cap)

    # Fuera del bloque with: el undo ya se ejecutó. Verificamos restauración exacta de estado.
    hp_restored_fp = compute_snapshot_fingerprint(_find_mesh_snapshot(high_poly_dag))
    rt_restored_fp = compute_snapshot_fingerprint(_find_mesh_snapshot(retopology_dag))

    scene_restored = (
        hp_restored_fp["structural_hash"] == hp_before_fp["structural_hash"]
        and rt_restored_fp["structural_hash"] == rt_before_fp["structural_hash"]
    )
    if not scene_restored:
        raise BridgeActionError(
            "PREVIEW_UNDO_INCOMPLETE",
            "El undo posterior al preview no restauró la huella exacta de la escena inicial.",
        )

    return {
        "operation_id": operation_id,
        "parameters": op_params,
        "operation_summary": op_summary,
        "proposed_changes": {
            "vertices_before": topology_before["vertex_count"],
            "vertices_after": topology_after["vertex_count"],
            "vertices_delta": topology_after["vertex_count"] - topology_before["vertex_count"],
            "edges_before": topology_before["edge_count"],
            "edges_after": topology_after["edge_count"],
            "edges_delta": topology_after["edge_count"] - topology_before["edge_count"],
            "faces_before": topology_before["face_count"],
            "faces_after": topology_after["face_count"],
            "faces_delta": topology_after["face_count"] - topology_before["face_count"],
        },
        "validation": {
            "passed": topology_after["is_all_quads"] and topology_after["is_clean_topology"],
            "is_all_quads": topology_after["is_all_quads"],
            "is_clean_topology": topology_after["is_clean_topology"],
            "high_poly_unchanged": True,
            "topology_after": topology_after,
        },
        "views": captured_views,
        "scene_restored": True,
        "high_poly_hash": hp_before_fp["structural_hash"],
        "retopology_initial_hash": rt_before_fp["structural_hash"],
    }
