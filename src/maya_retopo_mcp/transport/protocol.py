"""Protocolo de mensajes JSON tipados entre `maya-retopo-mcp` y `maya_bridge`."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from maya_retopo_mcp.errors import ErrorDetail, SecurityPolicyError, TransportError

ACTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def validate_action_name(action: str) -> str:
    """Garantiza que el identificador de acción siga estrictamente `namespace.action`."""
    if not isinstance(action, str) or not ACTION_NAME_RE.match(action):
        raise SecurityPolicyError(
            code="INVALID_ACTION_IDENTIFIER",
            message=f"Identificador de acción inválido: '{action}'.",
            recoverable=False,
            suggestion="Use únicamente identificadores registrados con formato 'namespace.action'.",
        )
    return action


@dataclass(frozen=True)
class BridgeRequest:
    """Mensaje enviado desde el servidor MCP hacia el puente en Maya."""

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        validate_action_name(self.action)
        if not isinstance(self.params, dict):
            raise SecurityPolicyError(
                code="INVALID_ACTION_PARAMS",
                message="Los parámetros enviados al puente deben ser un objeto JSON (dict).",
                recoverable=False,
            )

    def to_bytes(self, *, max_payload_bytes: int = 1_048_576) -> bytes:
        payload = {
            "request_id": self.request_id,
            "action": self.action,
            "params": self.params,
        }
        raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(raw) > max_payload_bytes:
            raise TransportError(
                code="REQUEST_PAYLOAD_TOO_LARGE",
                message=f"El mensaje hacia Maya ({len(raw)} bytes) excede el límite de {max_payload_bytes} bytes.",
                recoverable=True,
                suggestion="Reduzca la cantidad de elementos o parámetros enviados en una sola llamada.",
            )
        return raw


@dataclass(frozen=True)
class BridgeResponse:
    """Respuesta estructurada devuelta por `maya_bridge`."""

    request_id: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    scene: str | None = None
    scene_modified: bool = False
    warnings: list[str] = field(default_factory=list)
    error: ErrorDetail | None = None


def decode_bridge_response(
    raw_bytes: bytes,
    *,
    expected_request_id: str | None = None,
    max_payload_bytes: int = 1_048_576,
) -> BridgeResponse:
    """
    Decodifica la respuesta recibida desde Maya, tolerando líneas de ruido previas de Maya
    (si existe un objeto JSON delimitado en la última línea no vacía) y rechazando respuestas
    truncadas o corruptas.
    """
    if not raw_bytes:
        raise TransportError(
            code="EMPTY_BRIDGE_RESPONSE",
            message="El puente de Maya cerró la conexión sin devolver datos.",
            recoverable=True,
            suggestion="Verifique que Maya siga en ejecución y que el puente no haya sido detenido.",
        )

    if len(raw_bytes) > max_payload_bytes:
        raise TransportError(
            code="RESPONSE_PAYLOAD_TOO_LARGE",
            message=f"La respuesta de Maya ({len(raw_bytes)} bytes) excede el máximo permitido ({max_payload_bytes} bytes).",
            recoverable=True,
            suggestion="Use paginación o filtros para limitar el tamaño de la respuesta.",
        )

    try:
        text = raw_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise TransportError(
            code="INVALID_BRIDGE_ENCODING",
            message="La respuesta recibida desde Maya no es UTF-8 válido.",
            recoverable=True,
        ) from exc

    if not text:
        raise TransportError(
            code="EMPTY_BRIDGE_RESPONSE",
            message="El puente de Maya devolvió una respuesta vacía.",
            recoverable=True,
        )

    # Si Maya imprimió ruido en stdout antes del JSON en commandPort, tomamos la última línea JSON válida
    candidate_lines = [line.strip() for line in text.splitlines() if line.strip()]
    parsed: dict[str, Any] | None = None
    last_err: Exception | None = None

    for line in reversed(candidate_lines):
        # Si hay ruido antes de '{' en la misma línea, intentar extraer desde el primer '{'
        brace_idx = line.find("{")
        candidate = line[brace_idx:] if brace_idx >= 0 else line
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "ok" in obj:
                parsed = obj
                break
        except json.JSONDecodeError as err:
            last_err = err

    if parsed is None:
        raise TransportError(
            code="INVALID_BRIDGE_RESPONSE",
            message="Respuesta JSON truncada, malformada o con ruido irreconocible desde Maya.",
            recoverable=True,
            suggestion="Reintente la operación o verifique el estado del puente en el Script Editor de Maya.",
        ) from last_err

    resp_id = str(parsed.get("request_id", ""))
    if expected_request_id and resp_id and resp_id != expected_request_id:
        raise TransportError(
            code="MISMATCHED_REQUEST_ID",
            message=f"El request_id devuelto ('{resp_id}') no coincide con el esperado ('{expected_request_id}').",
            recoverable=True,
            suggestion="Reconecte con el puente de Maya para limpiar respuestas desincronizadas.",
        )

    ok = bool(parsed.get("ok", False))
    scene = parsed.get("scene")
    scene_modified = bool(parsed.get("scene_modified", False))
    warnings = [str(w) for w in parsed.get("warnings", []) if isinstance(w, str)]

    if not ok:
        raw_err = parsed.get("error") or {}
        if not isinstance(raw_err, dict):
            raw_err = {"code": "MAYA_BRIDGE_ERROR", "message": str(raw_err)}
        err_detail = ErrorDetail(
            code=str(raw_err.get("code", "MAYA_BRIDGE_ERROR")),
            message=str(raw_err.get("message", "Error reportado por el puente de Maya.")),
            recoverable=bool(raw_err.get("recoverable", True)),
            suggestion=str(raw_err.get("suggestion", "Revise los logs locales del puente en Maya.")),
        )
        return BridgeResponse(
            request_id=resp_id,
            ok=False,
            data={},
            scene=scene if isinstance(scene, str) else None,
            scene_modified=scene_modified,
            warnings=warnings,
            error=err_detail,
        )

    data = parsed.get("data") or {}
    if not isinstance(data, dict):
        raise TransportError(
            code="INVALID_BRIDGE_DATA",
            message="El campo 'data' devuelto por Maya no es un objeto JSON válido.",
            recoverable=True,
        )

    return BridgeResponse(
        request_id=resp_id,
        ok=True,
        data=data,
        scene=scene if isinstance(scene, str) else None,
        scene_modified=scene_modified,
        warnings=warnings,
        error=None,
    )
