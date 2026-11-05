"""Captura segura del viewport y restauración garantizada del estado previo (Fase 1)."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ViewportStateSnapshot:
    """Instantánea del estado del viewport y selección antes de una captura."""

    panel: str = "modelPanel4"
    camera: str = "persp"
    wireframe_on_shaded: bool = False
    isolate_enabled: bool = False
    selection: list[str] = field(default_factory=list)
    scene_modified: bool = False


def write_minimal_png(path: Path, width: int, height: int) -> None:
    """
    Escribe un archivo PNG válido de 1x1 escalado en metadatos (o dimensiones indicadas)
    para pruebas sin GUI o fallback de playblast en modo simulado.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Usamos un PNG válido compacto (1x1 RGB gris oscuro) para no consumir memoria innecesaria en tests
    raw_row = b"\x00\x28\x2c\x34"

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(raw_row)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )
    _ = width, height
    path.write_bytes(png_bytes)


def capture_viewport_with_restore(
    *,
    cmds: Any | None,
    camera: str = "persp",
    width: int = 1024,
    height: int = 1024,
    wireframe_on_shaded: bool = True,
    isolate: list[str] | None = None,
    frame_selected: bool = True,
    output_path: str | None = None,
    simulated_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Captura una imagen del viewport asegurando en un bloque `try ... finally` que
    la cámara, wireframeOnShaded, isolateSelect, selección y flag `modified` vuelvan
    exactamente a su estado original (Sección 6: `viewport.capture`).
    """
    isolate_nodes = list(isolate or [])

    if cmds is not None:
        panel = "modelPanel4"
        try:
            panels = cmds.getPanel(type="modelPanel") or []
            if panels and panel not in panels:
                panel = str(panels[0])
        except Exception:
            pass

        prev_sel = list(cmds.ls(selection=True, long=True) or [])
        prev_mod = bool(cmds.file(query=True, modified=True))
        try:
            prev_cam = str(cmds.modelEditor(panel, query=True, camera=True) or "persp")
            prev_wos = bool(cmds.modelEditor(panel, query=True, wireframeOnShaded=True))
            prev_iso = bool(cmds.isolateSelect(panel, query=True, state=True))
        except Exception:
            prev_cam = "persp"
            prev_wos = False
            prev_iso = False

        snapshot = ViewportStateSnapshot(
            panel=panel,
            camera=prev_cam,
            wireframe_on_shaded=prev_wos,
            isolate_enabled=prev_iso,
            selection=prev_sel,
            scene_modified=prev_mod,
        )

        restored = False
        try:
            cmds.lookThru(panel, camera)
            cmds.modelEditor(panel, edit=True, displayAppearance="smoothShaded", wireframeOnShaded=wireframe_on_shaded)
            if isolate_nodes:
                cmds.select(isolate_nodes, replace=True)
                cmds.isolateSelect(panel, state=True)
                cmds.isolateSelect(panel, addSelected=True)
            if frame_selected:
                cmds.viewFit(camera, all=not bool(isolate_nodes))

            if output_path:
                target = Path(output_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                cmds.playblast(
                    completeFilename=str(target),
                    format="image",
                    compression="png",
                    frame=cmds.currentTime(query=True),
                    widthHeight=(width, height),
                    viewer=False,
                    showOrnaments=False,
                    offScreen=True,
                    percent=100,
                )
        finally:
            try:
                cmds.isolateSelect(snapshot.panel, state=snapshot.isolate_enabled)
                cmds.modelEditor(
                    snapshot.panel,
                    edit=True,
                    wireframeOnShaded=snapshot.wireframe_on_shaded,
                )
                cmds.lookThru(snapshot.panel, snapshot.camera)
                if snapshot.selection:
                    cmds.select(snapshot.selection, replace=True)
                else:
                    cmds.select(clear=True)
                cmds.file(modified=snapshot.scene_modified)
                restored = True
            except Exception:
                restored = False

        return {
            "camera": camera,
            "width": width,
            "height": height,
            "wireframe_on_shaded": wireframe_on_shaded,
            "isolated_nodes": isolate_nodes,
            "frame_selected": frame_selected,
            "image_path": output_path,
            "viewport_state_restored": restored,
            "previous_state": {
                "panel": snapshot.panel,
                "camera": snapshot.camera,
                "wireframe_on_shaded": snapshot.wireframe_on_shaded,
                "isolate_enabled": snapshot.isolate_enabled,
            },
        }

    # Modo simulado (para pruebas deterministas sin Maya GUI)
    sim = simulated_state if simulated_state is not None else {}
    orig_cam = str(sim.get("camera", "persp"))
    orig_wos = bool(sim.get("wireframe_on_shaded", False))
    orig_iso = list(sim.get("isolated_nodes", []))
    orig_sel = list(sim.get("selection", []))
    orig_mod = bool(sim.get("modified", False))

    restored = False
    try:
        sim["camera"] = camera
        sim["wireframe_on_shaded"] = wireframe_on_shaded
        sim["isolated_nodes"] = list(isolate_nodes)
        if sim.get("fail_during_capture"):
            raise RuntimeError("Error simulado durante playblast del viewport.")
        if output_path:
            write_minimal_png(Path(output_path), width=width, height=height)
    finally:
        sim["camera"] = orig_cam
        sim["wireframe_on_shaded"] = orig_wos
        sim["isolated_nodes"] = orig_iso
        sim["selection"] = orig_sel
        sim["modified"] = orig_mod
        restored = True

    return {
        "camera": camera,
        "width": width,
        "height": height,
        "wireframe_on_shaded": wireframe_on_shaded,
        "isolated_nodes": isolate_nodes,
        "frame_selected": frame_selected,
        "image_path": output_path,
        "viewport_state_restored": restored,
        "previous_state": {
            "panel": "modelPanel4",
            "camera": orig_cam,
            "wireframe_on_shaded": orig_wos,
            "isolate_enabled": bool(orig_iso),
        },
    }
