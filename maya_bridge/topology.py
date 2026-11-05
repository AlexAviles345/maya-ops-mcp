"""Módulo puro y de extracción OpenMaya para análisis topológico determinista (Fase 1)."""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MeshGeometrySnapshot:
    """Representación geométrica y topológica agnóstica para análisis determinista."""

    transform_dag_path: str
    shape_dag_path: str
    uuid: str
    vertices: list[tuple[float, float, float]]
    faces: list[tuple[int, ...]]
    visible: bool = True
    intermediate_object: bool = False
    normals_inconsistent_override: int | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def bounding_box(self) -> tuple[float, float, float, float, float, float]:
        if not self.vertices:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.vertices]
        ys = [p[1] for p in self.vertices]
        zs = [p[2] for p in self.vertices]
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def compute_euler_characteristic(vertices: int, edges: int, faces: int) -> int:
    """Calcula la característica de Euler: V - E + F."""
    return int(vertices) - int(edges) + int(faces)


def _vec_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec_length(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _polygon_area(verts: list[tuple[float, float, float]], face: tuple[int, ...]) -> float:
    if len(face) < 3:
        return 0.0
    p0 = verts[face[0]]
    total_cross = [0.0, 0.0, 0.0]
    for i in range(1, len(face) - 1):
        v1 = _vec_sub(verts[face[i]], p0)
        v2 = _vec_sub(verts[face[i + 1]], p0)
        cr = _vec_cross(v1, v2)
        total_cross[0] += cr[0]
        total_cross[1] += cr[1]
        total_cross[2] += cr[2]
    return 0.5 * math.sqrt(
        total_cross[0] ** 2 + total_cross[1] ** 2 + total_cross[2] ** 2
    )


def _build_edge_Structures(
    faces: list[tuple[int, ...]],
) -> tuple[
    list[tuple[int, int]],
    dict[tuple[int, int], int],
    dict[int, list[tuple[int, int]]],
]:
    """
    Construye:
    - `edges`: lista determinista de aristas `(u, v)` con `u < v`.
    - `edge_to_id`: mapa `(u, v) -> edge_id`.
    - `edge_to_face_windings`: mapa `edge_id -> list[(face_idx, direction)]`
      donde `direction = +1` si la cara recorre `u -> v`, o `-1` si recorre `v -> u`.
    """
    edges: list[tuple[int, int]] = []
    edge_to_id: dict[tuple[int, int], int] = {}
    edge_to_face_windings: dict[int, list[tuple[int, int]]] = {}

    for f_idx, face in enumerate(faces):
        n = len(face)
        if n < 2:
            continue
        for i in range(n):
            u_raw = face[i]
            v_raw = face[(i + 1) % n]
            if u_raw == v_raw:
                continue
            u, v = (u_raw, v_raw) if u_raw < v_raw else (v_raw, u_raw)
            direction = 1 if u_raw < v_raw else -1
            key = (u, v)
            e_id = edge_to_id.get(key)
            if e_id is None:
                e_id = len(edges)
                edges.append(key)
                edge_to_id[key] = e_id
                edge_to_face_windings[e_id] = []
            edge_to_face_windings[e_id].append((f_idx, direction))

    return edges, edge_to_id, edge_to_face_windings


def _count_shells(vertex_count: int, faces: list[tuple[int, ...]]) -> int:
    """Calcula la cantidad de shells poligonales conexos por vértices compartidos."""
    if not faces:
        return 0

    vert_to_faces: dict[int, list[int]] = {}
    for f_idx, face in enumerate(faces):
        for v in face:
            vert_to_faces.setdefault(v, []).append(f_idx)

    visited_faces = [False] * len(faces)
    shells = 0
    for start_f in range(len(faces)):
        if visited_faces[start_f]:
            continue
        shells += 1
        queue: deque[int] = deque([start_f])
        visited_faces[start_f] = True
        while queue:
            curr_f = queue.popleft()
            for v in faces[curr_f]:
                for neighbor_f in vert_to_faces.get(v, ()):
                    if not visited_faces[neighbor_f]:
                        visited_faces[neighbor_f] = True
                        queue.append(neighbor_f)
    _ = vertex_count
    return shells


def _detect_non_manifold_vertices(
    vertex_count: int,
    faces: list[tuple[int, ...]],
    non_manifold_edge_verts: set[int],
) -> list[int]:
    """
    Detecta vértices non-manifold:
    1) Vértices pertenecientes a aristas non-manifold.
    2) Vértices cuyas caras incidentes forman más de un abanico conexo por aristas (bowtie vertex).
    """
    vert_to_faces: dict[int, list[int]] = {}
    for f_idx, face in enumerate(faces):
        for v in set(face):
            vert_to_faces.setdefault(v, []).append(f_idx)

    non_manifold_verts: set[int] = set(non_manifold_edge_verts)

    for v_idx in range(vertex_count):
        inc_faces = vert_to_faces.get(v_idx, [])
        if len(inc_faces) <= 1 or v_idx in non_manifold_verts:
            continue

        # Dos caras incidentes en v_idx están conectadas en el abanico si comparten otro vértice además de v_idx
        face_sets = {f: set(faces[f]) - {v_idx} for f in inc_faces}
        visited: set[int] = {inc_faces[0]}
        queue: deque[int] = deque([inc_faces[0]])
        while queue:
            curr = queue.popleft()
            curr_neighbors = face_sets[curr]
            for other in inc_faces:
                if other not in visited and (curr_neighbors & face_sets[other]):
                    visited.add(other)
                    queue.append(other)

        if len(visited) < len(inc_faces):
            non_manifold_verts.add(v_idx)

    return sorted(non_manifold_verts)


def _find_coincident_vertices(
    vertices: list[tuple[float, float, float]],
    tolerance: float = 1e-4,
) -> list[list[int]]:
    """Agrupa vértices distintos cuya distancia euclidiana es <= tolerance usando celdas espaciales."""
    if not vertices or tolerance <= 0:
        return []

    cell_size = max(tolerance, 1e-7)
    grid: dict[tuple[int, int, int], list[int]] = {}
    for idx, (x, y, z) in enumerate(vertices):
        cell = (
            int(math.floor(x / cell_size)),
            int(math.floor(y / cell_size)),
            int(math.floor(z / cell_size)),
        )
        grid.setdefault(cell, []).append(idx)

    adj: dict[int, set[int]] = {}
    tol_sq = tolerance * tolerance

    for (cx, cy, cz), indices in grid.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neighbor_indices = grid.get((cx + dx, cy + dy, cz + dz))
                    if not neighbor_indices:
                        continue
                    for i in indices:
                        pi = vertices[i]
                        for j in neighbor_indices:
                            if j <= i:
                                continue
                            pj = vertices[j]
                            dist_sq = (
                                (pi[0] - pj[0]) ** 2
                                + (pi[1] - pj[1]) ** 2
                                + (pi[2] - pj[2]) ** 2
                            )
                            if dist_sq <= tol_sq:
                                adj.setdefault(i, set()).add(j)
                                adj.setdefault(j, set()).add(i)

    visited: set[int] = set()
    groups: list[list[int]] = []
    for v_idx in sorted(adj.keys()):
        if v_idx in visited:
            continue
        comp: list[int] = []
        queue: deque[int] = deque([v_idx])
        visited.add(v_idx)
        while queue:
            curr = queue.popleft()
            comp.append(curr)
            for nb in sorted(adj.get(curr, ())):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        comp.sort()
        if len(comp) > 1:
            groups.append(comp)

    return groups


def extract_boundary_loops(snapshot: MeshGeometrySnapshot) -> dict[str, Any]:
    """
    Extrae y clasifica todos los grupos conexos de aristas de frontera (Sección 6: `retopo.boundary_loops`).
    """
    edges, _, edge_to_face_windings = _build_edge_Structures(snapshot.faces)
    boundary_edge_ids = [
        e_id for e_id, incidences in edge_to_face_windings.items() if len(incidences) == 1
    ]

    vert_to_b_edges: dict[int, list[int]] = {}
    for e_id in boundary_edge_ids:
        u, v = edges[e_id]
        vert_to_b_edges.setdefault(u, []).append(e_id)
        vert_to_b_edges.setdefault(v, []).append(e_id)

    mesh_bbox = snapshot.bounding_box
    visited_edges: set[int] = set()
    loops: list[dict[str, Any]] = []

    for start_edge in sorted(boundary_edge_ids):
        if start_edge in visited_edges:
            continue

        comp_edges: list[int] = []
        comp_verts: set[int] = set()
        queue: deque[int] = deque([start_edge])
        visited_edges.add(start_edge)

        while queue:
            curr_e = queue.popleft()
            comp_edges.append(curr_e)
            u, v = edges[curr_e]
            comp_verts.add(u)
            comp_verts.add(v)
            for endpoint in (u, v):
                for next_e in vert_to_b_edges.get(endpoint, ()):
                    if next_e not in visited_edges:
                        visited_edges.add(next_e)
                        queue.append(next_e)

        comp_edges.sort()
        sorted_verts = sorted(comp_verts)
        degrees = [len(vert_to_b_edges.get(v_id, ())) for v_id in sorted_verts]

        if any(d > 2 for d in degrees):
            topology_type = "branching"
        elif all(d == 2 for d in degrees) and len(comp_edges) >= 3:
            topology_type = "closed_loop"
        else:
            topology_type = "open_chain"

        pts = [snapshot.vertices[v_id] for v_id in sorted_verts if 0 <= v_id < len(snapshot.vertices)]
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            loop_bbox = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
            center = [
                round(sum(xs) / len(pts), 5),
                round(sum(ys) / len(pts), 5),
                round(sum(zs) / len(pts), 5),
            ]
        else:
            loop_bbox = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            center = [0.0, 0.0, 0.0]

        suggested_region = _suggest_anatomical_region(center, mesh_bbox)

        loops.append(
            {
                "loop_index": len(loops),
                "edge_ids": comp_edges,
                "vertex_ids": sorted_verts,
                "edge_count": len(comp_edges),
                "vertex_count": len(sorted_verts),
                "topology_type": topology_type,
                "is_closed_loop": topology_type == "closed_loop",
                "center": center,
                "bounding_box": [round(val, 5) for val in loop_bbox],
                "suggested_region": suggested_region,
            }
        )

    return {
        "dag_path": snapshot.transform_dag_path,
        "shape_dag_path": snapshot.shape_dag_path,
        "total_boundary_edges": len(boundary_edge_ids),
        "boundary_loop_count": len(loops),
        "loops": loops,
        "region_disclaimer": (
            "La región anatómica es una estimación heurística espacial como sugerencia; "
            "no debe tratarse como verdad absoluta sin confirmación del artista."
        ),
    }


def _suggest_anatomical_region(
    center: list[float],
    mesh_bbox: tuple[float, float, float, float, float, float],
) -> str:
    """Heurística espacial para sugerir región anatómica relativa al bounding box de la malla."""
    xmin, ymin, zmin, xmax, ymax, zmax = mesh_bbox
    height = max(ymax - ymin, 1e-5)
    width = max(xmax - xmin, 1e-5)
    x_mid = 0.5 * (xmin + xmax)

    rel_y = (center[1] - ymin) / height
    rel_x_abs = abs(center[0] - x_mid) / (0.5 * width)
    _ = zmin, zmax

    if rel_y >= 0.82:
        return "head_or_neck"
    if rel_y <= 0.15:
        return "feet_or_ankles"
    if rel_x_abs >= 0.65 and 0.35 <= rel_y <= 0.80:
        return "hands_or_wrists"
    if 0.40 <= rel_y < 0.82 and rel_x_abs < 0.65:
        return "torso_or_chest"
    return "limbs_or_transition"


def analyze_mesh_topology(
    snapshot: MeshGeometrySnapshot,
    *,
    zero_edge_tolerance: float = 1e-5,
    zero_area_tolerance: float = 1e-7,
    coincident_tolerance: float = 1e-4,
) -> dict[str, Any]:
    """
    Ejecuta el análisis topológico determinista completo (Sección 6: `retopo.analyze_mesh`).
    """
    v_count = len(snapshot.vertices)
    f_count = len(snapshot.faces)
    edges, _, edge_to_face_windings = _build_edge_Structures(snapshot.faces)
    e_count = len(edges)

    triangles: list[int] = []
    quads: list[int] = []
    ngons: list[int] = []
    invalid_faces: list[int] = []
    zero_area_faces: list[int] = []
    seen_face_signatures: dict[tuple[int, ...], int] = {}
    lamina_faces: list[int] = []

    for f_idx, face in enumerate(snapshot.faces):
        deg = len(face)
        valid_indices = all(0 <= v < v_count for v in face)
        if deg < 3 or len(set(face)) < 3 or not valid_indices:
            invalid_faces.append(f_idx)
        elif deg == 3:
            triangles.append(f_idx)
        elif deg == 4:
            quads.append(f_idx)
        else:
            ngons.append(f_idx)

        if deg >= 3 and valid_indices:
            area = _polygon_area(snapshot.vertices, face)
            if area <= zero_area_tolerance:
                zero_area_faces.append(f_idx)

        sig = tuple(sorted(face))
        if sig in seen_face_signatures:
            lamina_faces.append(f_idx)
        else:
            seen_face_signatures[sig] = f_idx

    boundary_edges: list[int] = []
    non_manifold_edges: list[int] = []
    non_manifold_edge_verts: set[int] = set()
    zero_length_edges: list[int] = []
    inconsistent_normal_edges = 0

    for e_id, (u, v) in enumerate(edges):
        incidences = edge_to_face_windings.get(e_id, [])
        if len(incidences) == 1:
            boundary_edges.append(e_id)
        elif len(incidences) > 2:
            non_manifold_edges.append(e_id)
            non_manifold_edge_verts.add(u)
            non_manifold_edge_verts.add(v)
        elif len(incidences) == 2:
            # En una superficie orientable consistente, las dos caras adyacentes
            # recorren la arista compartida en sentidos opuestos (+1 y -1).
            if incidences[0][1] == incidences[1][1]:
                inconsistent_normal_edges += 1

        if 0 <= u < v_count and 0 <= v < v_count:
            length = _vec_length(_vec_sub(snapshot.vertices[u], snapshot.vertices[v]))
            if length <= zero_edge_tolerance:
                zero_length_edges.append(e_id)

    non_manifold_vertices = _detect_non_manifold_vertices(
        v_count, snapshot.faces, non_manifold_edge_verts
    )
    coincident_groups = _find_coincident_vertices(snapshot.vertices, tolerance=coincident_tolerance)
    coincident_count = sum(len(g) for g in coincident_groups)
    shells = _count_shells(v_count, snapshot.faces)
    euler = compute_euler_characteristic(v_count, e_count, f_count)
    boundary_info = extract_boundary_loops(snapshot)
    quad_ratio = (len(quads) / f_count) if f_count > 0 else 0.0

    inconsistent_normals = (
        snapshot.normals_inconsistent_override
        if snapshot.normals_inconsistent_override is not None
        else inconsistent_normal_edges
    )

    return {
        "dag_path": snapshot.transform_dag_path,
        "shape_dag_path": snapshot.shape_dag_path,
        "uuid": snapshot.uuid,
        "vertex_count": v_count,
        "edge_count": e_count,
        "face_count": f_count,
        "face_types": {
            "triangles": len(triangles),
            "quads": len(quads),
            "ngons": len(ngons),
            "invalid_faces": len(invalid_faces),
            "quad_ratio": round(quad_ratio, 6),
            "quad_percentage": round(quad_ratio * 100.0, 2),
        },
        "face_type_ids": {
            "triangles": triangles[:200],
            "ngons": ngons[:200],
            "invalid_faces": invalid_faces[:200],
        },
        "boundary_edges": {
            "count": len(boundary_edges),
            "loop_count": boundary_info["boundary_loop_count"],
            "is_watertight": len(boundary_edges) == 0,
            "edge_ids_sample": boundary_edges[:200],
        },
        "non_manifold": {
            "edges_count": len(non_manifold_edges),
            "vertices_count": len(non_manifold_vertices),
            "edge_ids": non_manifold_edges[:200],
            "vertex_ids": non_manifold_vertices[:200],
        },
        "degeneracies": {
            "lamina_faces_count": len(lamina_faces),
            "lamina_face_ids": lamina_faces[:200],
            "zero_length_edges_count": len(zero_length_edges),
            "zero_length_edge_ids": zero_length_edges[:200],
            "zero_area_faces_count": len(zero_area_faces),
            "zero_area_face_ids": zero_area_faces[:200],
            "coincident_vertex_groups_count": len(coincident_groups),
            "coincident_vertex_count": coincident_count,
            "coincident_vertex_groups": coincident_groups[:100],
            "coincident_tolerance": coincident_tolerance,
        },
        "shells": shells,
        "euler_characteristic": euler,
        "normals": {
            "inconsistent_winding_edges_count": inconsistent_normals,
            "consistent": inconsistent_normals == 0,
        },
        "bounding_box": [round(val, 5) for val in snapshot.bounding_box],
        "is_all_quads": f_count > 0 and len(quads) == f_count,
        "is_clean_topology": (
            f_count > 0
            and len(quads) == f_count
            and len(non_manifold_edges) == 0
            and len(non_manifold_vertices) == 0
            and len(lamina_faces) == 0
            and len(zero_length_edges) == 0
            and len(zero_area_faces) == 0
            and inconsistent_normals == 0
        ),
    }


def summarize_mesh_for_listing(snapshot: MeshGeometrySnapshot) -> dict[str, Any]:
    """Resumen ligero de una shape poligonal para `scene.list_meshes` (Sección 6)."""
    v_count = len(snapshot.vertices)
    f_count = len(snapshot.faces)
    edges, _, edge_to_face_windings = _build_edge_Structures(snapshot.faces)
    e_count = len(edges)

    tri_count = 0
    quad_count = 0
    ngon_count = 0
    for face in snapshot.faces:
        deg = len(face)
        if deg == 3:
            tri_count += 1
        elif deg == 4:
            quad_count += 1
        elif deg > 4:
            ngon_count += 1

    boundary_edge_count = sum(1 for inc in edge_to_face_windings.values() if len(inc) == 1)
    shells = _count_shells(v_count, snapshot.faces)

    return {
        "transform_dag_path": snapshot.transform_dag_path,
        "shape_dag_path": snapshot.shape_dag_path,
        "uuid": snapshot.uuid,
        "vertex_count": v_count,
        "edge_count": e_count,
        "face_count": f_count,
        "face_types": {
            "triangles": tri_count,
            "quads": quad_count,
            "ngons": ngon_count,
        },
        "shells": shells,
        "boundary_edges": boundary_edge_count,
        "is_watertight": boundary_edge_count == 0 and f_count > 0,
        "bounding_box": [round(val, 5) for val in snapshot.bounding_box],
        "visible": snapshot.visible,
        "intermediate_object": snapshot.intermediate_object,
    }


def _bbox_spatial_relation(
    bbox_a: list[float] | tuple[float, ...],
    bbox_b: list[float] | tuple[float, ...],
) -> dict[str, float]:
    """Calcula la superposición espacial (IoU 3D y distancia relativa entre centros) de dos BBoxes."""
    ax0, ay0, az0, ax1, ay1, az1 = bbox_a
    bx0, by0, bz0, bx1, by1, bz1 = bbox_b

    ix0, iy0, iz0 = max(ax0, bx0), max(ay0, by0), max(az0, bz0)
    ix1, iy1, iz1 = min(ax1, bx1), min(ay1, by1), min(az1, bz1)

    inter_vol = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0) * max(0.0, iz1 - iz0)
    vol_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0) * max(0.0, az1 - az0)
    vol_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0) * max(0.0, bz1 - bz0)
    union_vol = vol_a + vol_b - inter_vol
    iou = (inter_vol / union_vol) if union_vol > 1e-9 else 0.0
    min_vol = min(vol_a, vol_b)
    containment = (inter_vol / min_vol) if min_vol > 1e-9 else 0.0

    ca = (0.5 * (ax0 + ax1), 0.5 * (ay0 + ay1), 0.5 * (az0 + az1))
    cb = (0.5 * (bx0 + bx1), 0.5 * (by0 + by1), 0.5 * (bz0 + bz1))
    center_dist = _vec_length(_vec_sub(ca, cb))

    ux0, uy0, uz0 = min(ax0, bx0), min(ay0, by0), min(az0, bz0)
    ux1, uy1, uz1 = max(ax1, bx1), max(ay1, by1), max(az1, bz1)
    union_diag = max(_vec_length((ux1 - ux0, uy1 - uy0, uz1 - uz0)), 1e-6)
    normalized_center_dist = center_dist / union_diag

    return {
        "bbox_iou": round(iou, 4),
        "bbox_containment": round(containment, 4),
        "center_distance": round(center_dist, 4),
        "normalized_center_distance": round(normalized_center_dist, 4),
    }


def detect_retopo_candidates(snapshots: list[MeshGeometrySnapshot]) -> dict[str, Any]:
    """
    Clasifica candidatos a `high_poly` y `retopology` usando evidencia geométrica y espacial,
    sin confirmar roles ni usar el nombre del nodo como única prueba (Sección 6: `retopo.detect_candidates`).
    """
    active_meshes = [
        summarize_mesh_for_listing(s)
        for s in snapshots
        if not s.intermediate_object and len(s.faces) > 0
    ]

    if not active_meshes:
        return {
            "roles_confirmed": False,
            "high_poly_candidates": [],
            "retopology_candidates": [],
            "spatial_pairs": [],
            "explanation": "No se encontraron mallas poligonales activas en la escena.",
        }

    max_faces = max(m["face_count"] for m in active_meshes)
    min_faces = min(m["face_count"] for m in active_meshes)

    high_poly_candidates: list[dict[str, Any]] = []
    retopology_candidates: list[dict[str, Any]] = []

    for m in active_meshes:
        f_count = m["face_count"]
        quads = m["face_types"]["quads"]
        tris = m["face_types"]["triangles"]
        ngons = m["face_types"]["ngons"]
        quad_ratio = quads / f_count if f_count > 0 else 0.0
        density_vs_min = round(f_count / max(min_faces, 1), 2)
        density_vs_max = round(f_count / max(max_faces, 1), 4)

        # Evidencia para high-poly: mayor densidad relativa o presencia de triangulación densa/escultura
        hp_reasons: list[str] = []
        hp_score = 0.0
        if len(active_meshes) > 1 and f_count == max_faces and density_vs_min >= 2.0:
            hp_score += 0.55
            hp_reasons.append(
                f"Mayor densidad poligonal de la escena ({f_count} caras, {density_vs_min}x respecto a la malla más ligera)."
            )
        if f_count >= 5000:
            hp_score += 0.25
            hp_reasons.append(f"Conteo elevado de caras ({f_count}) típico de escultura de referencia.")
        if m["is_watertight"]:
            hp_score += 0.10
            hp_reasons.append("Malla cerrada sin bordes abiertos (watertight).")
        if tris > 0 or quad_ratio < 0.95:
            hp_score += 0.10
            hp_reasons.append(
                f"Distribución mixta de caras (quads={quads}, triángulos={tris}, n-gons={ngons})."
            )

        if hp_score >= 0.45:
            high_poly_candidates.append(
                {
                    "dag_path": m["transform_dag_path"],
                    "shape_dag_path": m["shape_dag_path"],
                    "uuid": m["uuid"],
                    "score": round(min(hp_score, 1.0), 3),
                    "evidence": {
                        "vertex_count": m["vertex_count"],
                        "edge_count": m["edge_count"],
                        "face_count": f_count,
                        "density_ratio_vs_lightest": density_vs_min,
                        "quad_ratio": round(quad_ratio, 4),
                        "shells": m["shells"],
                        "boundary_edges": m["boundary_edges"],
                        "is_watertight": m["is_watertight"],
                    },
                    "reasons": hp_reasons,
                }
            )

        # Evidencia para retopología manual: menor densidad, predominancia de quads, posibles bordes abiertos en progreso
        rt_reasons: list[str] = []
        rt_score = 0.0
        if len(active_meshes) > 1 and f_count < max_faces and density_vs_max <= 0.5:
            rt_score += 0.45
            rt_reasons.append(
                f"Densidad reducida apta para retopología ({f_count} caras, {round(density_vs_max * 100, 2)}% de la malla más densa)."
            )
        if quad_ratio >= 0.85:
            rt_score += 0.35
            rt_reasons.append(
                f"Predominio de quads ({round(quad_ratio * 100, 1)}% quads; triángulos={tris}, n-gons={ngons})."
            )
        if m["boundary_edges"] > 0:
            rt_score += 0.20
            rt_reasons.append(
                f"Presenta {m['boundary_edges']} aristas de frontera abiertas (retopología en progreso o por regiones)."
            )

        if rt_score >= 0.45:
            retopology_candidates.append(
                {
                    "dag_path": m["transform_dag_path"],
                    "shape_dag_path": m["shape_dag_path"],
                    "uuid": m["uuid"],
                    "score": round(min(rt_score, 1.0), 3),
                    "evidence": {
                        "vertex_count": m["vertex_count"],
                        "edge_count": m["edge_count"],
                        "face_count": f_count,
                        "density_ratio_vs_heaviest": density_vs_max,
                        "quad_ratio": round(quad_ratio, 4),
                        "shells": m["shells"],
                        "boundary_edges": m["boundary_edges"],
                        "is_watertight": m["is_watertight"],
                    },
                    "reasons": rt_reasons,
                }
            )

    high_poly_candidates.sort(key=lambda item: item["score"], reverse=True)
    retopology_candidates.sort(key=lambda item: item["score"], reverse=True)

    mesh_by_dag = {m["transform_dag_path"]: m for m in active_meshes}
    spatial_pairs: list[dict[str, Any]] = []
    for hp in high_poly_candidates:
        for rt in retopology_candidates:
            if hp["dag_path"] == rt["dag_path"]:
                continue
            m_hp = mesh_by_dag[hp["dag_path"]]
            m_rt = mesh_by_dag[rt["dag_path"]]
            rel = _bbox_spatial_relation(m_hp["bounding_box"], m_rt["bounding_box"])
            density_ratio = round(m_hp["face_count"] / max(m_rt["face_count"], 1), 2)
            spatial_pairs.append(
                {
                    "high_poly_candidate": hp["dag_path"],
                    "retopology_candidate": rt["dag_path"],
                    "face_density_ratio": density_ratio,
                    "spatial_relation": rel,
                    "co_located": rel["bbox_containment"] >= 0.5 or rel["normalized_center_distance"] <= 0.25,
                }
            )

    return {
        "roles_confirmed": False,
        "confirmation_required": True,
        "high_poly_candidates": high_poly_candidates,
        "retopology_candidates": retopology_candidates,
        "spatial_pairs": spatial_pairs,
        "explanation": (
            "Clasificación basada estrictamente en densidad V/E/F, proporción de quads, "
            "shells, fronteras abiertas y superposición espacial de bounding boxes. "
            "El artista debe confirmar explícitamente los roles con retopo.confirm_roles."
        ),
    }


def compute_snapshot_fingerprint(snapshot: MeshGeometrySnapshot) -> dict[str, Any]:
    """
    Calcula la huella estructural de una malla (`dag_path`, `uuid`, conteos V/E/F,
    `bounding_box` y `structural_hash` SHA-256 sobre topología y posiciones) compatible con
    `MeshFingerprint` de `src/maya_retopo_mcp/policies/protected_mesh.py`.
    """
    edges, _, _ = _build_edge_Structures(snapshot.faces)
    v_count = len(snapshot.vertices)
    e_count = len(edges)
    f_count = len(snapshot.faces)
    bbox = snapshot.bounding_box
    sampled_points = snapshot.vertices[:2048]

    payload = {
        "dag_path": snapshot.transform_dag_path,
        "uuid": snapshot.uuid,
        "v": v_count,
        "e": e_count,
        "f": f_count,
        "bbox": [round(val, 5) for val in bbox],
        "points": [[round(c, 5) for c in pt] for pt in sampled_points],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    structural_hash = hashlib.sha256(serialized).hexdigest()

    return {
        "dag_path": snapshot.transform_dag_path,
        "shape_dag_path": snapshot.shape_dag_path,
        "uuid": snapshot.uuid,
        "vertex_count": v_count,
        "edge_count": e_count,
        "face_count": f_count,
        "bounding_box": [round(val, 5) for val in bbox],
        "structural_hash": structural_hash,
    }
