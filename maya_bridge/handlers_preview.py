"""Handlers de modo `PREVIEW` (Fase 2: selección y confirmación de roles; Fase 3: preview regional)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from maya_bridge.handlers_read import (
    _extract_scene_meshes,
    _find_mesh_snapshot,
    _get_maya_cmds,
    get_simulated_state,
    handle_selection_get,
)
from maya_bridge.topology import compute_snapshot_fingerprint


class BridgeActionError(RuntimeError):
    """Error tipado dentro del puente de Maya con código estructurado."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@contextmanager
def maya_undo_chunk(chunk_name: str, *, always_undo: bool = True) -> Iterator[None]:
    """
    Ejecuta un bloque dentro de un undo chunk de Maya.
    Si `always_undo=True` (modo PREVIEW) o si ocurre una excepción, revierte automáticamente.
    """
    cmds = _get_maya_cmds()
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


def execute_with_rollback_on_error(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Ejecuta `fn` dentro de un undo chunk que hace undo automático si ocurre un error."""
    with maya_undo_chunk("maya_retopo_mcp_op", always_undo=False):
        return fn(*args, **kwargs)


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
    Confirma `high_poly` y `retopology` mediante DAG paths explícitos o selección actual del artista,
    y calcula las huellas estructurales para activar la protección de la high-poly.
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
