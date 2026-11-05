"""Detección determinista del plano anatómico de simetría sin asumir X = 0 (Fase 1)."""

from __future__ import annotations

import math
from typing import Any

from maya_bridge.topology import MeshGeometrySnapshot

AXIS_TO_INDEX: dict[str, int] = {"X": 0, "Y": 1, "Z": 2}


def _estimate_axis_offset(
    vertices: list[tuple[float, float, float]],
    axis_idx: int,
) -> float:
    """
    Estima el offset real del plano bilateral para el eje indicado sin asumir que es 0.0.
    Combina el punto medio del bounding box y la mediana de coordenadas para robustez frente
    a densidad asimétrica local.
    """
    if not vertices:
        return 0.0
    coords = sorted(v[axis_idx] for v in vertices)
    n = len(coords)
    bbox_mid = 0.5 * (coords[0] + coords[-1])
    median = coords[n // 2] if (n % 2 == 1) else 0.5 * (coords[n // 2 - 1] + coords[n // 2])
    mean = sum(coords) / n

    # Probamos los tres estimadores candidatos y elegimos el que minimice el error de reflexión
    candidates = [bbox_mid, median, mean]
    best_offset = bbox_mid
    best_median_dist = float("inf")

    for cand in candidates:
        dists = _compute_reflection_distances(vertices, axis_idx, cand)
        sorted_d = sorted(dists)
        med_d = sorted_d[len(sorted_d) // 2]
        if med_d < best_median_dist:
            best_median_dist = med_d
            best_offset = cand

    return round(best_offset, 6)


def _compute_reflection_distances(
    vertices: list[tuple[float, float, float]],
    axis_idx: int,
    plane_offset: float,
) -> list[float]:
    """
    Para cada vértice, refleja su posición respecto al plano `coord[axis_idx] = plane_offset`
    y calcula la distancia euclidiana al vértice más cercano de la malla.
    """
    n = len(vertices)
    if n == 0:
        return []

    distances: list[float] = []
    for i in range(n):
        vx, vy, vz = vertices[i]
        if axis_idx == 0:
            rx, ry, rz = (2.0 * plane_offset - vx, vy, vz)
        elif axis_idx == 1:
            rx, ry, rz = (vx, 2.0 * plane_offset - vy, vz)
        else:
            rx, ry, rz = (vx, vy, 2.0 * plane_offset - vz)

        min_dist_sq = float("inf")
        for j in range(n):
            px, py, pz = vertices[j]
            d_sq = (rx - px) ** 2 + (ry - py) ** 2 + (rz - pz) ** 2
            if d_sq < min_dist_sq:
                min_dist_sq = d_sq
                if d_sq <= 1e-12:
                    break
        distances.append(math.sqrt(min_dist_sq))

    return distances


def evaluate_axis_symmetry(
    vertices: list[tuple[float, float, float]],
    axis_name: str,
    *,
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """Evalúa un eje específico (`X`, `Y` o `Z`) como candidato de simetría bilateral."""
    axis_idx = AXIS_TO_INDEX[axis_name]
    v_count = len(vertices)
    if v_count == 0:
        return {
            "axis": axis_name,
            "plane_offset": 0.0,
            "paired_count": 0,
            "paired_percentage": 0.0,
            "mean_error": 0.0,
            "max_error": 0.0,
            "unpaired_vertex_ids": [],
            "score": 0.0,
        }

    offset = _estimate_axis_offset(vertices, axis_idx)
    distances = _compute_reflection_distances(vertices, axis_idx, offset)

    paired_indices = [idx for idx, d in enumerate(distances) if d <= tolerance]
    unpaired_indices = [idx for idx, d in enumerate(distances) if d > tolerance]

    paired_pct = (len(paired_indices) / v_count) * 100.0
    mean_err = sum(distances) / v_count
    max_err = max(distances)

    # Puntaje normalizado en [0, 1] ponderando emparejamiento y precisión geométrica
    error_penalty = 1.0 / (1.0 + (mean_err / max(tolerance, 1e-5)))
    score = (paired_pct / 100.0) * 0.75 + error_penalty * 0.25

    return {
        "axis": axis_name,
        "plane_offset": round(offset, 5),
        "paired_count": len(paired_indices),
        "paired_percentage": round(paired_pct, 2),
        "mean_error": round(mean_err, 6),
        "max_error": round(max_err, 6),
        "unpaired_count": len(unpaired_indices),
        "unpaired_vertex_ids": unpaired_indices[:100],
        "score": round(score, 4),
    }


def analyze_mesh_symmetry(
    snapshot: MeshGeometrySnapshot,
    *,
    tolerance: float = 0.05,
) -> dict[str, Any]:
    """
    Evalúa X, Y y Z como posibles ejes bilaterales sin asumir X = 0 y devuelve el plano recomendado
    con su offset real, errores, porcentaje con pareja, asimetrías y nivel de confianza
    (Sección 6: `retopo.analyze_symmetry`).
    """
    evaluations = {
        axis: evaluate_axis_symmetry(snapshot.vertices, axis, tolerance=tolerance)
        for axis in ("X", "Y", "Z")
    }

    ranked = sorted(
        evaluations.values(),
        key=lambda ev: (ev["score"], ev["paired_percentage"], -ev["mean_error"]),
        reverse=True,
    )
    best = ranked[0]

    paired_pct = best["paired_percentage"]
    mean_err = best["mean_error"]
    if paired_pct >= 90.0 and mean_err <= tolerance * 0.5:
        confidence = "HIGH"
    elif paired_pct >= 70.0 and mean_err <= tolerance:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    unpaired_ids: list[int] = best["unpaired_vertex_ids"]
    asymmetric_summary: list[dict[str, Any]] = []
    if unpaired_ids:
        pts = [snapshot.vertices[idx] for idx in unpaired_ids if 0 <= idx < len(snapshot.vertices)]
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            zs = [p[2] for p in pts]
            asymmetric_summary.append(
                {
                    "vertex_count": best["unpaired_count"],
                    "sample_vertex_ids": unpaired_ids[:25],
                    "bounding_box": [
                        round(min(xs), 5),
                        round(min(ys), 5),
                        round(min(zs), 5),
                        round(max(xs), 5),
                        round(max(ys), 5),
                        round(max(zs), 5),
                    ],
                }
            )

    return {
        "dag_path": snapshot.transform_dag_path,
        "shape_dag_path": snapshot.shape_dag_path,
        "recommended_axis": best["axis"],
        "plane_equation": f"{best['axis']} = {best['plane_offset']}",
        "plane_offset": best["plane_offset"],
        "NonZeroOffsetDetected": abs(best["plane_offset"]) > 1e-4,
        "mean_error": best["mean_error"],
        "max_error": best["max_error"],
        "paired_percentage": best["paired_percentage"],
        "paired_count": best["paired_count"],
        "vertex_count": len(snapshot.vertices),
        "tolerance": tolerance,
        "confidence": confidence,
        "confidence_score": best["score"],
        "asymmetric_regions": asymmetric_summary,
        "axis_evaluations": evaluations,
        "symmetry_applied": False,
    }
