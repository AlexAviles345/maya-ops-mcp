"""Despachador cerrado de handlers dentro de Autodesk Maya (sin eval/exec arbitrario)."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from maya_bridge.handlers_preview import (
    handle_retopo_confirm_roles,
    handle_retopo_preview_region,
    handle_safety_checkpoint,
    handle_selection_set,
)
from maya_bridge.handlers_read import (
    get_current_scene_state,
    handle_maya_health,
    handle_retopo_analyze_mesh,
    handle_retopo_analyze_symmetry,
    handle_retopo_boundary_loops,
    handle_retopo_detect_candidates,
    handle_scene_describe,
    handle_scene_list_meshes,
    handle_selection_get,
    handle_viewport_capture,
)

HandlerFunc = Callable[[dict[str, Any]], dict[str, Any]]

ALLOWED_HANDLERS: dict[str, HandlerFunc] = {
    "maya.health": handle_maya_health,
    "scene.describe": handle_scene_describe,
    "scene.list_meshes": handle_scene_list_meshes,
    "selection.get": handle_selection_get,
    "selection.set": handle_selection_set,
    "retopo.detect_candidates": handle_retopo_detect_candidates,
    "retopo.confirm_roles": handle_retopo_confirm_roles,
    "retopo.analyze_mesh": handle_retopo_analyze_mesh,
    "retopo.analyze_symmetry": handle_retopo_analyze_symmetry,
    "retopo.boundary_loops": handle_retopo_boundary_loops,
    "viewport.capture": handle_viewport_capture,
    "safety.checkpoint": handle_safety_checkpoint,
    "retopo.preview_region": handle_retopo_preview_region,
}


class BridgeDispatcher:
    """
    Despacha mensajes JSON exclusivamente a handlers registrados en `ALLOWED_HANDLERS`.
    Garantiza exclusión mutua para devolver `MAYA_BUSY` si Maya está procesando otra orden.
    """

    def __init__(self, handlers: dict[str, HandlerFunc] | None = None) -> None:
        self._handlers: dict[str, HandlerFunc] = dict(handlers or ALLOWED_HANDLERS)
        self._busy_lock = threading.Lock()

    def register_handler(self, action: str, handler: HandlerFunc) -> None:
        self._handlers[action] = handler

    def dispatch_raw(self, raw_line: bytes) -> bytes:
        """Procesa una línea JSON y devuelve una línea JSON serializada en UTF-8."""
        response_dict = self._dispatch_to_dict(raw_line)
        return (json.dumps(response_dict, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def _dispatch_to_dict(self, raw_line: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_line.decode("utf-8").strip())
        except Exception:
            return {
                "request_id": "",
                "ok": False,
                "scene": None,
                "scene_modified": False,
                "error": {
                    "code": "INVALID_JSON_REQUEST",
                    "message": "El mensaje recibido por maya_bridge no es JSON válido.",
                    "recoverable": True,
                    "suggestion": "Envíe una solicitud JSON bien formada.",
                },
            }

        if not isinstance(payload, dict):
            return {
                "request_id": "",
                "ok": False,
                "scene": None,
                "scene_modified": False,
                "error": {
                    "code": "INVALID_REQUEST_OBJECT",
                    "message": "El payload debe ser un objeto JSON.",
                    "recoverable": True,
                    "suggestion": "Envíe un diccionario con request_id, action y params.",
                },
            }

        request_id = str(payload.get("request_id", ""))
        action = str(payload.get("action", ""))
        params = payload.get("params") or {}

        if not isinstance(params, dict):
            return {
                "request_id": request_id,
                "ok": False,
                "scene": None,
                "scene_modified": False,
                "error": {
                    "code": "INVALID_ACTION_PARAMS",
                    "message": "El campo 'params' debe ser un objeto JSON.",
                    "recoverable": True,
                    "suggestion": "Proporcione un objeto JSON para params.",
                },
            }

        handler = self._handlers.get(action)
        if handler is None:
            scene_name, modified = get_current_scene_state()
            return {
                "request_id": request_id,
                "ok": False,
                "scene": scene_name,
                "scene_modified": modified,
                "error": {
                    "code": "UNSUPPORTED_BRIDGE_ACTION",
                    "message": f"La acción '{action}' no está registrada en maya_bridge.",
                    "recoverable": False,
                    "suggestion": "Use únicamente acciones permitidas y registradas en el puente.",
                },
            }

        acquired = self._busy_lock.acquire(blocking=False)
        if not acquired:
            scene_name, modified = get_current_scene_state()
            return {
                "request_id": request_id,
                "ok": False,
                "scene": scene_name,
                "scene_modified": modified,
                "error": {
                    "code": "MAYA_BUSY",
                    "message": "Maya se encuentra ejecutando otra operación en este momento.",
                    "recoverable": True,
                    "suggestion": "Espere a que finalice la operación actual y reintente.",
                },
            }

        try:
            data = self._execute_in_maya_main_thread(handler, params)
            scene_name, modified = get_current_scene_state()
            if "scene" in data and scene_name is None:
                scene_name = data.get("scene")
            if "modified" in data and not modified:
                modified = bool(data.get("modified", False))
            return {
                "request_id": request_id,
                "ok": True,
                "scene": scene_name,
                "scene_modified": modified,
                "data": data,
                "warnings": [],
            }
        except Exception as exc:
            scene_name, modified = get_current_scene_state()
            err_code = getattr(exc, "code", "BRIDGE_HANDLER_FAILED")
            return {
                "request_id": request_id,
                "ok": False,
                "scene": scene_name,
                "scene_modified": modified,
                "error": {
                    "code": str(err_code),
                    "message": f"Fallo al ejecutar '{action}': {exc}",
                    "recoverable": True,
                    "suggestion": "Verifique el estado de la escena en Maya o restaure el último checkpoint.",
                },
            }
        finally:
            self._busy_lock.release()

    @staticmethod
    def _execute_in_maya_main_thread(handler: HandlerFunc, params: dict[str, Any]) -> dict[str, Any]:
        """Si `maya.utils` está disponible en Maya GUI, despacha al hilo principal."""
        try:
            import maya.utils as mu  # type: ignore[import-not-found]

            if hasattr(mu, "executeInMainThreadWithResult"):
                return mu.executeInMainThreadWithResult(handler, params)  # type: ignore[no-any-return]
        except ImportError:
            pass
        return handler(params)

