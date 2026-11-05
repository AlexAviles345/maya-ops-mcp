"""Handler regional registrado: `feet_v1` (extrusión de quads puros para región de pies/tobillos)."""

from __future__ import annotations

from typing import Any

from maya_bridge.topology import MeshGeometrySnapshot
from operations import extrude_boundary_quad_ring


def execute_feet_v1(
    snapshot: MeshGeometrySnapshot,
    parameters: dict[str, Any],
) -> tuple[MeshGeometrySnapshot, dict[str, Any]]:
    """Extiende el anillo inferior de frontera hacia los pies manteniendo topología 100% quads."""
    step_y = float(parameters.get("step_y", -8.0))
    scale = float(parameters.get("scale", 0.95))
    ring = list(parameters.get("ring_vertices", [0, 1, 2, 3]))

    updated = extrude_boundary_quad_ring(
        snapshot,
        ring_vertices=[int(v) for v in ring],
        offset_vector=(0.0, step_y, 0.0),
        scale_factor=scale,
    )
    return updated, {
        "operation_id": "feet_v1",
        "region": "feet_or_ankles",
        "added_vertices": len(updated.vertices) - len(snapshot.vertices),
        "added_quad_faces": len(updated.faces) - len(snapshot.faces),
        "parameters_applied": {"step_y": step_y, "scale": scale},
    }
