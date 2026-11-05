"""Handlers de solo lectura ejecutados dentro de Maya (Fase 0 y Fase 1)."""

from __future__ import annotations

import sys
from typing import Any

from maya_bridge.symmetry import analyze_mesh_symmetry
from maya_bridge.topology import (
    MeshGeometrySnapshot,
    analyze_mesh_topology,
    detect_retopo_candidates,
    extract_boundary_loops,
    summarize_mesh_for_listing,
)
from maya_bridge.viewport import capture_viewport_with_restore

TIME_UNIT_FPS_MAP: dict[str, float] = {
    "game": 15.0,
    "film": 24.0,
    "pal": 25.0,
    "ntsc": 30.0,
    "show": 48.0,
    "palf": 50.0,
    "ntscf": 60.0,
    "23.976fps": 23.976,
    "29.97fps": 29.97,
    "59.94fps": 59.94,
}


def _get_maya_cmds() -> Any | None:
    """Importa `maya.cmds` únicamente cuando el puente corre dentro de Maya."""
    try:
        import maya.cmds as cmds  # type: ignore[import-not-found]

        return cmds
    except ImportError:
        return None


def _get_openmaya() -> Any | None:
    """Importa `maya.api.OpenMaya` (API 2.0) únicamente dentro de Maya."""
    try:
        import maya.api.OpenMaya as om2  # type: ignore[import-not-found]

        return om2
    except ImportError:
        return None


def _build_default_simulated_meshes() -> list[MeshGeometrySnapshot]:
    """
    Construye una escena simulada determinista (inspirada en el flujo MICEL) para pruebas
    sin Maya abierto:
    1) `|escultura_ref`: malla densa cerrada (triángulos + quads) desplazada en X = 1.25.
    2) `|retopo_cuerpo`: malla de retopología exclusivamente en quads, simétrica respecto
       al plano X = 1.25, con bordes abiertos en cuello/manos/pies.
    """
    offset_x = 1.25
    # Malla de retopología: cilindro/torso abierto de quads puros centrado en X = 1.25
    # 3 anillos verticales (y = 10, 50, 90) de 4 vértices cada uno -> 2 niveles de 4 quads = 8 quads, 12 vértices
    # Dos loops de frontera cerrados: inferior (y=10, pies/tobillos) y superior (y=90, cabeza/cuello)
    retopo_verts: list[tuple[float, float, float]] = [
        # Anillo 0 (y = 10.0)
        (offset_x - 10.0, 10.0, -10.0),
        (offset_x + 10.0, 10.0, -10.0),
        (offset_x + 10.0, 10.0, 10.0),
        (offset_x - 10.0, 10.0, 10.0),
        # Anillo 1 (y = 50.0)
        (offset_x - 12.0, 50.0, -10.0),
        (offset_x + 12.0, 50.0, -10.0),
        (offset_x + 12.0, 50.0, 10.0),
        (offset_x - 12.0, 50.0, 10.0),
        # Anillo 2 (y = 90.0)
        (offset_x - 8.0, 90.0, -8.0),
        (offset_x + 8.0, 90.0, -8.0),
        (offset_x + 8.0, 90.0, 8.0),
        (offset_x - 8.0, 90.0, 8.0),
    ]
    retopo_faces: list[tuple[int, ...]] = [
        # Nivel inferior (anillo 0 -> anillo 1)
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
        # Nivel superior (anillo 1 -> anillo 2)
        (4, 5, 9, 8),
        (5, 6, 10, 9),
        (6, 7, 11, 10),
        (7, 4, 8, 11),
    ]

    # Escultura high-poly simulada: subdivisión densa y cerrada en el mismo volumen espacial
    hp_verts: list[tuple[float, float, float]] = list(retopo_verts)
    hp_faces: list[tuple[int, ...]] = []
    # Triangulamos y replicamos capas sobre el volumen para tener alta densidad (> 6x caras) y cierre watertight
    base_box_verts = [
        (offset_x - 12.0, 10.0, -10.0),
        (offset_x + 12.0, 10.0, -10.0),
        (offset_x + 12.0, 10.0, 10.0),
        (offset_x - 12.0, 10.0, 10.0),
        (offset_x - 12.0, 90.0, -10.0),
        (offset_x + 12.0, 90.0, -10.0),
        (offset_x + 12.0, 90.0, 10.0),
        (offset_x - 12.0, 90.0, 10.0),
    ]
    hp_verts = list(base_box_verts)
    # 12 triángulos cerrados (watertight) + subdivisión por caras para mayor densidad
    closed_tris: list[tuple[int, ...]] = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    ]
    # Subdividir cada triángulo 1->3 dos veces (12 * 3 * 3 = 108 caras cerradas) manteniendo cierre exacto
    curr_tris = closed_tris
    for _ in range(2):
        next_tris: list[tuple[int, ...]] = []
        for a, b, c in curr_tris:
            pa, pb, pc = hp_verts[a], hp_verts[b], hp_verts[c]
            mid = (
                (pa[0] + pb[0] + pc[0]) / 3.0,
                (pa[1] + pb[1] + pc[1]) / 3.0,
                (pa[2] + pb[2] + pc[2]) / 3.0,
            )
            m_idx = len(hp_verts)
            hp_verts.append(mid)
            next_tris.append((a, b, m_idx))
            next_tris.append((b, c, m_idx))
            next_tris.append((c, a, m_idx))
        curr_tris = next_tris
    hp_faces = curr_tris

    return [
        MeshGeometrySnapshot(
            transform_dag_path="|escultura_ref",
            shape_dag_path="|escultura_ref|escultura_refShape",
            uuid="AAAA1111-BBBB-2222-CCCC-333333333333",
            vertices=hp_verts,
            faces=hp_faces,
            visible=True,
            intermediate_object=False,
        ),
        MeshGeometrySnapshot(
            transform_dag_path="|retopo_cuerpo",
            shape_dag_path="|retopo_cuerpo|retopo_cuerpoShape",
            uuid="DDDD4444-EEEE-5555-FFFF-666666666666",
            vertices=retopo_verts,
            faces=retopo_faces,
            visible=True,
            intermediate_object=False,
        ),
    ]


_SIMULATED_STATE: dict[str, Any] = {
    "scene": "C:/proyecto/output/micel_v001.mb",
    "modified": False,
    "linear_unit": "cm",
    "angular_unit": "deg",
    "time_unit": "film",
    "up_axis": "y",
    "selection": ["|retopo_cuerpo"],
    "meshes": _build_default_simulated_meshes(),
    "viewport": {
        "camera": "persp",
        "wireframe_on_shaded": False,
        "isolated_nodes": [],
    },
}


def get_simulated_state() -> dict[str, Any]:
    """Devuelve el diccionario de estado simulado para pruebas sin Maya."""
    return _SIMULATED_STATE


def reset_simulated_state() -> None:
    """Restaura el estado simulado a los valores iniciales de prueba."""
    _SIMULATED_STATE.clear()
    _SIMULATED_STATE.update(
        {
            "scene": "C:/proyecto/output/micel_v001.mb",
            "modified": False,
            "linear_unit": "cm",
            "angular_unit": "deg",
            "time_unit": "film",
            "up_axis": "y",
            "selection": ["|retopo_cuerpo"],
            "meshes": _build_default_simulated_meshes(),
            "viewport": {
                "camera": "persp",
                "wireframe_on_shaded": False,
                "isolated_nodes": [],
            },
        }
    )


def get_current_scene_state() -> tuple[str | None, bool]:
    """Devuelve `(scene_path, modified)` sin alterar el estado de la escena."""
    cmds = _get_maya_cmds()
    if cmds is None:
        return (
            _SIMULATED_STATE.get("scene"),
            bool(_SIMULATED_STATE.get("modified", False)),
        )
    try:
        scene_name = cmds.file(query=True, sceneName=True) or None
        modified = bool(cmds.file(query=True, modified=True))
        return (scene_name, modified)
    except Exception:
        return (None, False)


def _extract_scene_meshes() -> list[MeshGeometrySnapshot]:
    """Extrae todas las shapes poligonales desde Maya (`OpenMaya` + `cmds`) o del estado simulado."""
    cmds = _get_maya_cmds()
    om2 = _get_openmaya()
    if cmds is None or om2 is None:
        return list(_SIMULATED_STATE.get("meshes", []))

    shapes = cmds.ls(type="mesh", long=True) or []
    snapshots: list[MeshGeometrySnapshot] = []

    for shape_dag in shapes:
        parents = cmds.listRelatives(shape_dag, parent=True, fullPath=True) or []
        transform_dag = str(parents[0]) if parents else str(shape_dag)
        uuids = cmds.ls(shape_dag, uuid=True) or [""]
        node_uuid = str(uuids[0])
        is_intermediate = bool(cmds.getAttr(f"{shape_dag}.intermediateObject"))
        is_visible = bool(cmds.getAttr(f"{shape_dag}.visibility")) and bool(
            cmds.getAttr(f"{transform_dag}.visibility")
        )

        try:
            sel = om2.MSelectionList()
            sel.add(shape_dag)
            dag_path = sel.getDagPath(0)
            fn_mesh = om2.MFnMesh(dag_path)
            pts = fn_mesh.getPoints(om2.MSpace.kWorld)
            vertices = [(float(p.x), float(p.y), float(p.z)) for p in pts]

            poly_iter = om2.MItMeshPolygon(dag_path)
            faces: list[tuple[int, ...]] = []
            while not poly_iter.isDone():
                v_indices = poly_iter.getVertices()
                faces.append(tuple(int(idx) for idx in v_indices))
                poly_iter.next()
        except Exception:
            vertices = []
            faces = []

        snapshots.append(
            MeshGeometrySnapshot(
                transform_dag_path=transform_dag,
                shape_dag_path=str(shape_dag),
                uuid=node_uuid,
                vertices=vertices,
                faces=faces,
                visible=is_visible,
                intermediate_object=is_intermediate,
            )
        )

    return snapshots


def _find_mesh_snapshot(dag_path: str) -> MeshGeometrySnapshot:
    """Busca una malla por `transform_dag_path` o `shape_dag_path`."""
    target = dag_path.strip()
    for snap in _extract_scene_meshes():
        if snap.transform_dag_path == target or snap.shape_dag_path == target:
            return snap
    raise ValueError(f"No se encontró la malla '{dag_path}' en la escena actual.")


def handle_maya_health(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `maya.health` dentro del puente de Maya."""
    _ = params
    cmds = _get_maya_cmds()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    if cmds is not None:
        maya_version = str(cmds.about(version=True))
        scene_name, modified = get_current_scene_state()
    else:
        maya_version = "2027"
        scene_name, modified = get_current_scene_state()

    return {
        "ok": True,
        "maya_version": maya_version,
        "python_version": py_ver,
        "scene": scene_name,
        "modified": modified,
    }


def handle_scene_describe(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `scene.describe` (Sección 6). Solo lectura."""
    _ = params
    cmds = _get_maya_cmds()
    scene_name, modified = get_current_scene_state()
    meshes = _extract_scene_meshes()

    if cmds is not None:
        linear_unit = str(cmds.currentUnit(query=True, linear=True))
        angular_unit = str(cmds.currentUnit(query=True, angle=True))
        time_unit = str(cmds.currentUnit(query=True, time=True))
        up_axis = str(cmds.upAxis(query=True, axis=True))
        assemblies = list(cmds.ls(assemblies=True, long=True) or [])
        cameras = list(cmds.ls(type="camera", long=True) or [])
        lights = list(cmds.ls(lights=True, long=True) or [])
        plugins = list(cmds.pluginInfo(query=True, listPlugins=True) or [])
    else:
        linear_unit = str(_SIMULATED_STATE.get("linear_unit", "cm"))
        angular_unit = str(_SIMULATED_STATE.get("angular_unit", "deg"))
        time_unit = str(_SIMULATED_STATE.get("time_unit", "film"))
        up_axis = str(_SIMULATED_STATE.get("up_axis", "y"))
        assemblies = [
            "|persp",
            "|top",
            "|front",
            "|side",
            *[m.transform_dag_path for m in meshes],
        ]
        cameras = ["|persp|perspShape", "|top|topShape", "|front|frontShape", "|side|sideShape"]
        lights = []
        plugins = ["modelingToolkit", "objExport", "fbxmaya"]

    fps = TIME_UNIT_FPS_MAP.get(time_unit.lower(), 24.0)

    return {
        "scene": scene_name,
        "modified": modified,
        "units": {
            "linear": linear_unit,
            "angular": angular_unit,
            "time": time_unit,
            "fps": fps,
        },
        "up_axis": up_axis,
        "root_assemblies": assemblies,
        "cameras": cameras,
        "lights": lights,
        "mesh_count": len([m for m in meshes if not m.intermediate_object]),
        "total_mesh_shapes": len(meshes),
        "loaded_plugins": plugins[:50],
    }


def handle_scene_list_meshes(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `scene.list_meshes` con soporte de paginación y filtros (Sección 6)."""
    offset = max(0, int(params.get("offset", 0)))
    limit = max(1, min(int(params.get("limit", 50)), 500))
    include_hidden = bool(params.get("include_hidden", True))
    include_intermediate = bool(params.get("include_intermediate", False))
    name_contains = str(params.get("name_contains", "")).strip().lower()
    min_faces = int(params.get("min_faces", 0))
    max_faces_raw = params.get("max_faces")
    max_faces = int(max_faces_raw) if max_faces_raw is not None else None

    all_snapshots = _extract_scene_meshes()
    filtered_items: list[dict[str, Any]] = []

    for snap in all_snapshots:
        if not include_intermediate and snap.intermediate_object:
            continue
        if not include_hidden and not snap.visible:
            continue
        if name_contains and (
            name_contains not in snap.transform_dag_path.lower()
            and name_contains not in snap.shape_dag_path.lower()
        ):
            continue
        f_count = len(snap.faces)
        if f_count < min_faces:
            continue
        if max_faces is not None and f_count > max_faces:
            continue
        filtered_items.append(summarize_mesh_for_listing(snap))

    total_count = len(filtered_items)
    paginated = filtered_items[offset : offset + limit]

    return {
        "total_count": total_count,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total_count,
        "meshes": paginated,
    }


def handle_selection_get(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `selection.get` con límite de expansión de componentes (Sección 6)."""
    max_components = max(1, min(int(params.get("max_components", 500)), 10_000))
    cmds = _get_maya_cmds()

    if cmds is not None:
        raw_sel = list(cmds.ls(selection=True, long=True) or [])
        expanded = list(cmds.ls(selection=True, long=True, flatten=True) or [])
    else:
        raw_sel = list(_SIMULATED_STATE.get("selection", []))
        expanded = list(raw_sel)

    objects = [item for item in expanded if "." not in item]
    components = [item for item in expanded if "." in item]

    if not expanded:
        mode = "empty"
    elif objects and components:
        mode = "mixed"
    elif components:
        mode = "component"
    else:
        mode = "object"

    truncated = len(components) > max_components

    return {
        "mode": mode,
        "raw_selection": raw_sel[:max_components],
        "objects": objects[:max_components],
        "components": components[:max_components],
        "object_count": len(objects),
        "component_count": len(components),
        "total_expanded_count": len(expanded),
        "max_components": max_components,
        "truncated": truncated,
    }


def handle_retopo_detect_candidates(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `retopo.detect_candidates` (Sección 6)."""
    _ = params
    snapshots = _extract_scene_meshes()
    return detect_retopo_candidates(snapshots)


def handle_retopo_analyze_mesh(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `retopo.analyze_mesh` (Sección 6)."""
    dag_path = str(params.get("dag_path", "")).strip()
    if not dag_path:
        raise ValueError("El parámetro 'dag_path' es obligatorio para retopo.analyze_mesh.")
    coincident_tol = float(params.get("coincident_tolerance", 1e-4))
    snap = _find_mesh_snapshot(dag_path)
    return analyze_mesh_topology(snap, coincident_tolerance=coincident_tol)


def handle_retopo_analyze_symmetry(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `retopo.analyze_symmetry` (Sección 6)."""
    dag_path = str(params.get("dag_path", "")).strip()
    if not dag_path:
        raise ValueError("El parámetro 'dag_path' es obligatorio para retopo.analyze_symmetry.")
    tolerance = float(params.get("tolerance", 0.05))
    snap = _find_mesh_snapshot(dag_path)
    return analyze_mesh_symmetry(snap, tolerance=tolerance)


def handle_retopo_boundary_loops(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `retopo.boundary_loops` (Sección 6)."""
    dag_path = str(params.get("dag_path", "")).strip()
    if not dag_path:
        raise ValueError("El parámetro 'dag_path' es obligatorio para retopo.boundary_loops.")
    snap = _find_mesh_snapshot(dag_path)
    return extract_boundary_loops(snap)


def handle_viewport_capture(params: dict[str, Any]) -> dict[str, Any]:
    """Handler de `viewport.capture` con restauración garantizada del estado del viewport."""
    camera = str(params.get("camera", "persp"))
    width = int(params.get("width", 1024))
    height = int(params.get("height", 1024))
    wireframe_on_shaded = bool(params.get("wireframe_on_shaded", True))
    isolate = [str(node) for node in (params.get("isolate") or [])]
    frame_selected = bool(params.get("frame_selected", True))
    output_path = params.get("output_path")

    cmds = _get_maya_cmds()
    return capture_viewport_with_restore(
        cmds=cmds,
        camera=camera,
        width=width,
        height=height,
        wireframe_on_shaded=wireframe_on_shaded,
        isolate=isolate,
        frame_selected=frame_selected,
        output_path=str(output_path) if output_path else None,
        simulated_state=_SIMULATED_STATE.get("viewport"),
    )
