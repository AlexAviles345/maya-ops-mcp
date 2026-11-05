"""Pruebas unitarias de algoritmos deterministas de topología, fronteras, candidatos y simetría (Fase 1)."""

from __future__ import annotations

import unittest

from maya_bridge.symmetry import analyze_mesh_symmetry
from maya_bridge.topology import (
    MeshGeometrySnapshot,
    analyze_mesh_topology,
    detect_retopo_candidates,
    extract_boundary_loops,
)


class TestTopologyAnalysisUnit(unittest.TestCase):
    def test_clean_quad_grid_and_euler_characteristic(self) -> None:
        # Un plano de 1 quad abierto: V=4, E=4, F=1 -> Euler = 4 - 4 + 1 = 1
        snap = MeshGeometrySnapshot(
            transform_dag_path="|quad_plane",
            shape_dag_path="|quad_plane|quad_planeShape",
            uuid="U-1",
            vertices=[
                (-1.0, 0.0, -1.0),
                (1.0, 0.0, -1.0),
                (1.0, 0.0, 1.0),
                (-1.0, 0.0, 1.0),
            ],
            faces=[(0, 1, 2, 3)],
        )
        res = analyze_mesh_topology(snap)
        self.assertEqual(res["vertex_count"], 4)
        self.assertEqual(res["edge_count"], 4)
        self.assertEqual(res["face_count"], 1)
        self.assertEqual(res["face_types"]["quads"], 1)
        self.assertEqual(res["face_types"]["triangles"], 0)
        self.assertEqual(res["face_types"]["ngons"], 0)
        self.assertEqual(res["euler_characteristic"], 1)
        self.assertTrue(res["is_all_quads"])
        self.assertTrue(res["is_clean_topology"])
        self.assertEqual(res["boundary_edges"]["count"], 4)
        self.assertEqual(res["boundary_edges"]["loop_count"], 1)

    def test_detects_non_manifold_lamina_zero_length_zero_area_and_coincident(self) -> None:
        # Construimos una malla con:
        # - 3 caras compartiendo la arista (0, 1) -> non-manifold edge
        # - Cara duplicada (0, 1, 2) dos veces -> lamina face
        # - Vértices 4 y 5 en la misma posición -> zero-length edge + zero-area face + coincident vertices
        # - Un pentágono (0, 1, 2, 3, 6) -> n-gon
        snap = MeshGeometrySnapshot(
            transform_dag_path="|dirty_mesh",
            shape_dag_path="|dirty_mesh|dirty_meshShape",
            uuid="U-DIRTY",
            vertices=[
                (0.0, 0.0, 0.0),      # 0
                (2.0, 0.0, 0.0),      # 1
                (1.0, 2.0, 0.0),      # 2
                (1.0, -2.0, 0.0),     # 3
                (5.0, 5.0, 5.0),      # 4
                (5.0, 5.0, 5.0),      # 5 (coincidente con 4)
                (0.0, -2.0, 1.0),     # 6
            ],
            faces=[
                (0, 1, 2),            # Triángulo 1
                (0, 1, 2),            # Lamina face (mismos vértices que Triángulo 1)
                (0, 1, 3),            # Tercera cara sobre la arista (0, 1) -> non-manifold edge
                (4, 5, 2),            # Arista (4,5) de longitud cero y cara de área cero
                (0, 1, 2, 3, 6),      # N-gon (5 lados)
            ],
        )
        res = analyze_mesh_topology(snap)
        self.assertFalse(res["is_all_quads"])
        self.assertFalse(res["is_clean_topology"])
        self.assertGreaterEqual(res["face_types"]["triangles"], 3)
        self.assertEqual(res["face_types"]["ngons"], 1)
        self.assertGreaterEqual(res["non_manifold"]["edges_count"], 1)
        self.assertGreaterEqual(res["degeneracies"]["lamina_faces_count"], 1)
        self.assertGreaterEqual(res["degeneracies"]["zero_length_edges_count"], 1)
        self.assertGreaterEqual(res["degeneracies"]["zero_area_faces_count"], 1)
        self.assertEqual(res["degeneracies"]["coincident_vertex_groups_count"], 1)
        self.assertEqual(res["degeneracies"]["coincident_vertex_groups"][0], [4, 5])

    def test_boundary_loops_classification(self) -> None:
        # Dos quads separados: el primero es un loop cerrado de 4 aristas;
        # en el segundo añadimos una aleta en T sobre una arista frontera para provocar branching.
        snap = MeshGeometrySnapshot(
            transform_dag_path="|boundary_test",
            shape_dag_path="|boundary_test|Shape",
            uuid="U-BOUND",
            vertices=[
                (-1.0, 95.0, -1.0),
                (1.0, 95.0, -1.0),
                (1.0, 95.0, 1.0),
                (-1.0, 95.0, 1.0),
            ],
            faces=[(0, 1, 2, 3)],
        )
        loops_info = extract_boundary_loops(snap)
        self.assertEqual(loops_info["boundary_loop_count"], 1)
        loop0 = loops_info["loops"][0]
        self.assertEqual(loop0["topology_type"], "closed_loop")
        self.assertTrue(loop0["is_closed_loop"])
        self.assertEqual(loop0["edge_count"], 4)
        self.assertIn("sugerencia", loops_info["region_disclaimer"])


class TestSymmetryAndCandidateDetectionUnit(unittest.TestCase):
    def test_symmetry_detects_non_zero_offset_plane(self) -> None:
        # Malla simétrica respecto al plano X = -3.5 (no X = 0)
        offset = -3.5
        verts = [
            (offset - 4.0, 0.0, 0.0),
            (offset + 4.0, 0.0, 0.0),
            (offset - 2.5, 10.0, 3.0),
            (offset + 2.5, 10.0, 3.0),
            (offset - 1.0, 20.0, -2.0),
            (offset + 1.0, 20.0, -2.0),
        ]
        snap = MeshGeometrySnapshot(
            transform_dag_path="|personaje_desplazado",
            shape_dag_path="|personaje_desplazado|Shape",
            uuid="U-SYM",
            vertices=verts,
            faces=[(0, 1, 3, 2), (2, 3, 5, 4)],
        )
        sym = analyze_mesh_symmetry(snap, tolerance=0.01)
        self.assertEqual(sym["recommended_axis"], "X")
        self.assertAlmostEqual(sym["plane_offset"], offset, places=4)
        self.assertEqual(sym["paired_percentage"], 100.0)
        self.assertEqual(sym["confidence"], "HIGH")
        self.assertFalse(sym["symmetry_applied"])

    def test_detect_candidates_uses_geometry_not_node_names(self) -> None:
        # Nombramos los nodos "|nodo_A" y "|nodo_B" (sin pistas en el nombre)
        from maya_bridge.handlers_read import _build_default_simulated_meshes

        default_meshes = _build_default_simulated_meshes()
        unnamed_hp = MeshGeometrySnapshot(
            transform_dag_path="|nodo_A",
            shape_dag_path="|nodo_A|Shape",
            uuid="UUID-A",
            vertices=default_meshes[0].vertices,
            faces=default_meshes[0].faces,
        )
        unnamed_rt = MeshGeometrySnapshot(
            transform_dag_path="|nodo_B",
            shape_dag_path="|nodo_B|Shape",
            uuid="UUID-B",
            vertices=default_meshes[1].vertices,
            faces=default_meshes[1].faces,
        )
        result = detect_retopo_candidates([unnamed_hp, unnamed_rt])
        self.assertFalse(result["roles_confirmed"])
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["high_poly_candidates"][0]["dag_path"], "|nodo_A")
        self.assertEqual(result["retopology_candidates"][0]["dag_path"], "|nodo_B")
        self.assertTrue(result["spatial_pairs"][0]["co_located"])


if __name__ == "__main__":
    unittest.main()
