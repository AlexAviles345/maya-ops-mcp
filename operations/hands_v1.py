"""Handler regional registrado: `hands_v1` (extrusión de quads puros para región de manos/muñecas)."""

from __future__ import annotations

from typing import Any

from maya_bridge.topology import MeshGeometrySnapshot
from operations import extrude_boundary_quad_ring


def execute_hands_v1(
    snapshot: MeshGeometrySnapshot,
    parameters: dict[str, Any],
) -> tuple[MeshGeometrySnapshot, dict[str, Any]]:
    """Extiende un anillo de frontera para muñecas/manos manteniendo topología 100% quads."""
    step_y = float(parameters.get("step_y", 6.0))
    scale = float(parameters.get("scale", 0.90))
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
        "operation_id": "hands_v1",
        "region": "hands_or_wrists",
        "added_vertices": len(updated.vertices) - len(snapshot.vertices),
        "added_quad_faces": len(updated.faces) - len(snapshot.faces),
        "parameters_applied": {"step_y": step_y, "scale": scale},
    }
