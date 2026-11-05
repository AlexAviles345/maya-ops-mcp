"""Protección y verificación de huella estructural de la escultura High-Poly (Sección 5)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from maya_retopo_mcp.errors import HighPolyChangedError


@dataclass(frozen=True)
class MeshFingerprint:
    """Huella inmutable de una malla (DAG path, UUID, conteos V/E/F, BBox y hash estructural)."""

    dag_path: str
    uuid: str
    vertex_count: int
    edge_count: int
    face_count: int
    bounding_box: tuple[float, float, float, float, float, float]
    structural_hash: str

    @classmethod
    def compute_hash(
        cls,
        *,
        dag_path: str,
        uuid: str,
        vertex_count: int,
        edge_count: int,
        face_count: int,
        bounding_box: tuple[float, float, float, float, float, float],
        sampled_points: list[tuple[float, float, float]] | None = None,
    ) -> str:
        """Calcula un hash determinista SHA-256 sobre topología, BBox y muestra de posiciones."""
        payload = {
            "dag_path": dag_path,
            "uuid": uuid,
            "v": vertex_count,
            "e": edge_count,
            "f": face_count,
            "bbox": [round(val, 5) for val in bounding_box],
            "points": [[round(c, 5) for c in pt] for pt in (sampled_points or [])],
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dag_path": self.dag_path,
            "uuid": self.uuid,
            "vertex_count": self.vertex_count,
            "edge_count": self.edge_count,
            "face_count": self.face_count,
            "bounding_box": list(self.bounding_box),
            "structural_hash": self.structural_hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MeshFingerprint:
        bbox_list = raw.get("bounding_box", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        if len(bbox_list) != 6:
            bbox_tuple = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        else:
            bbox_tuple = (
                float(bbox_list[0]),
                float(bbox_list[1]),
                float(bbox_list[2]),
                float(bbox_list[3]),
                float(bbox_list[4]),
                float(bbox_list[5]),
            )
        return cls(
            dag_path=str(raw["dag_path"]),
            uuid=str(raw["uuid"]),
            vertex_count=int(raw["vertex_count"]),
            edge_count=int(raw["edge_count"]),
            face_count=int(raw["face_count"]),
            bounding_box=bbox_tuple,
            structural_hash=str(raw["structural_hash"]),
        )

    def verify_matches(self, current: MeshFingerprint, *, bbox_tolerance: float = 1e-4) -> None:
        """Comprueba que `current` coincida exactamente con la huella protegida."""
        if (
            self.dag_path != current.dag_path
            or self.uuid != current.uuid
            or self.vertex_count != current.vertex_count
            or self.edge_count != current.edge_count
            or self.face_count != current.face_count
            or self.structural_hash != current.structural_hash
        ):
            raise HighPolyChangedError()

        for expected_val, actual_val in zip(self.bounding_box, current.bounding_box, strict=True):
            if abs(expected_val - actual_val) > bbox_tolerance:
                raise HighPolyChangedError()

