"""Funciones puras y de consulta para análisis topológico determinista (Fase 1)."""

from __future__ import annotations


def compute_euler_characteristic(vertices: int, edges: int, faces: int) -> int:
    """Calcula la característica de Euler: V - E + F."""
    return int(vertices) - int(edges) + int(faces)

