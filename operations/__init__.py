"""Operaciones regionales registradas y auditadas para Maya Retopo MCP (quads puros)."""

from __future__ import annotations

from typing import Any

from maya_bridge.topology import MeshGeometrySnapshot


def extrude_boundary_quad_ring(
    snapshot: MeshGeometrySnapshot,
    *,
    ring_vertices: list[int],
    offset_vector: tuple[float, float, float],
    scale_factor: float = 1.0,
) -> MeshGeometrySnapshot:
    """
    Extiende un anillo ordenado de vértices de frontera creando un nuevo anillo de vértices
    y conectándolos exclusivamente mediante caras de 4 lados (quads) con orientación consistente.
    """
    if len(ring_vertices) < 3:
        raise ValueError("Se requieren al menos 3 vértices en el anillo para extruir quads.")

    new_verts = list(snapshot.vertices)
    new_faces = list(snapshot.faces)

    pts = [new_verts[idx] for idx in ring_vertices]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    cz = sum(p[2] for p in pts) / len(pts)

    extruded_indices: list[int] = []
    ox, oy, oz = offset_vector
    for idx in ring_vertices:
        vx, vy, vz = new_verts[idx]
        nx = cx + (vx - cx) * scale_factor + ox
        ny = cy + (vy - cy) * scale_factor + oy
        nz = cz + (vz - cz) * scale_factor + oz
        extruded_indices.append(len(new_verts))
        new_verts.append((round(nx, 5), round(ny, 5), round(nz, 5)))

    # Determinar el sentido de las caras existentes sobre las aristas del anillo para conservar normales consistentes
    existing_directed_edges: set[tuple[int, int]] = set()
    for face in snapshot.faces:
        m = len(face)
        for i in range(m):
            existing_directed_edges.add((face[i], face[(i + 1) % m]))

    n = len(ring_vertices)
    for i in range(n):
        u = ring_vertices[i]
        v = ring_vertices[(i + 1) % n]
        u_ext = extruded_indices[i]
        v_ext = extruded_indices[(i + 1) % n]
        # Si una cara existente recorre (u -> v), la nueva cara adyacente debe recorrer (v -> u)
        if (u, v) in existing_directed_edges:
            new_faces.append((v, u, u_ext, v_ext))
        else:
            new_faces.append((u, v, v_ext, u_ext))

    return MeshGeometrySnapshot(
        transform_dag_path=snapshot.transform_dag_path,
        shape_dag_path=snapshot.shape_dag_path,
        uuid=snapshot.uuid,
        vertices=new_verts,
        faces=new_faces,
        visible=snapshot.visible,
        intermediate_object=snapshot.intermediate_object,
        normals_inconsistent_override=snapshot.normals_inconsistent_override,
        extra_metadata=dict(snapshot.extra_metadata),
    )


def dispatch_registered_operation(
    operation_id: str,
    snapshot: MeshGeometrySnapshot,
    parameters: dict[str, Any],
) -> tuple[MeshGeometrySnapshot, dict[str, Any]]:
    """Despacha exclusivamente a los handlers regionales registrados."""
    from operations.feet_v1 import execute_feet_v1
    from operations.hands_v1 import execute_hands_v1
    from operations.head_face_v1 import execute_head_face_v1

    registry = {
        "feet_v1": execute_feet_v1,
        "hands_v1": execute_hands_v1,
        "head_face_v1": execute_head_face_v1,
    }
    handler = registry.get(operation_id)
    if handler is None:
        raise ValueError(f"Operación regional no registrada: '{operation_id}'.")
    return handler(snapshot, parameters)
