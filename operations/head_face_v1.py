"""Handler regional registrado: `head_face_v1` (extrusión de quads puros para región de cabeza/rostro)."""

from __future__ import annotations

from typing import Any

from maya_bridge.topology import MeshGeometrySnapshot
from operations import extrude_boundary_quad_ring


def execute_head_face_v1(
    snapshot: MeshGeometrySnapshot,
    parameters: dict[str, Any],
) -> tuple[MeshGeometrySnapshot, dict[str, Any]]:
    """Extiende el anillo superior de frontera hacia cuello/cabeza manteniendo topología 100% quads."""
    step_y = float(parameters.get("step_y", 10.0))
    scale = float(parameters.get("scale", 1.05))
    n_verts = len(snapshot.vertices)
    default_ring = [n_verts - 4, n_verts - 3, n_verts - 2, n_verts - 1] if n_verts >= 4 else [0, 1, 2, 3]
    ring = list(parameters.get("ring_vertices", default_ring))

    updated = extrude_boundary_quad_ring(
        snapshot,
        ring_vertices=[int(v) for v in ring],
        offset_vector=(0.0, step_y, 0.0),
        scale_factor=scale,
    )
    return updated, {
        "operation_id": "head_face_v1",
        "region": "head_or_neck",
        "added_vertices": len(updated.vertices) - len(snapshot.vertices),
        "added_quad_faces": len(updated.faces) - len(snapshot.faces),
        "parameters_applied": {"step_y": step_y, "scale": scale},
    }
