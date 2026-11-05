"""Cliente TCP loopback seguro hacia el puente en Autodesk Maya (`command_port`)."""

from __future__ import annotations

import socket
import time
from typing import Any

from maya_retopo_mcp.config import ServerConfig, validate_loopback_host
from maya_retopo_mcp.errors import TransportError
from maya_retopo_mcp.transport.protocol import (
    BridgeRequest,
    BridgeResponse,
    decode_bridge_response,
)


class MayaLoopbackClient:
    """
    Cliente de transporte TCP que se conecta exclusivamente a loopback (`127.0.0.1` o `localhost`)
    para enviar acciones tipadas a `maya_bridge` y recibir respuestas JSON acotadas.
    """

    def __init__(self, config: ServerConfig, *, max_retries: int = 1, retry_backoff_sec: float = 0.05) -> None:
        self._config = config
        self._host = validate_loopback_host(config.maya_host)
        self._port = config.maya_port
        self._max_retries = max(0, max_retries)
        self._retry_backoff_sec = max(0.0, retry_backoff_sec)

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def send_action(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> BridgeResponse:
        """Envía una solicitud JSON tipada a Maya y devuelve el `BridgeResponse` validado."""
        request = BridgeRequest(action=action, params=params or {})
        payload_bytes = request.to_bytes(max_payload_bytes=self._config.max_payload_bytes)
        effective_timeout = timeout_sec if timeout_sec is not None else self._config.timeout_sec

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._execute_single_request(
                    request=request,
                    payload_bytes=payload_bytes,
                    timeout_sec=effective_timeout,
                )
            except TransportError as err:
                last_exc = err
                # No reintentar en timeout o payload excesivo para no duplicar carga sobre Maya
                if err.detail.code in {
                    "MAYA_TIMEOUT",
                    "RESPONSE_PAYLOAD_TOO_LARGE",
                    "REQUEST_PAYLOAD_TOO_LARGE",
                }:
                    raise
                if attempt < self._max_retries:
                    time.sleep(self._retry_backoff_sec)
                else:
                    raise

        assert last_exc is not None
        raise last_exc

    def _execute_single_request(
        self,
        *,
        request: BridgeRequest,
        payload_bytes: bytes,
        timeout_sec: float,
    ) -> BridgeResponse:
        chunks: list[bytes] = []
        total_read = 0
        max_bytes = self._config.max_payload_bytes

        try:
            with socket.create_connection((self._host, self._port), timeout=timeout_sec) as sock:
                sock.settimeout(timeout_sec)
                sock.sendall(payload_bytes)
                try:
                    sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    total_read += len(chunk)
                    if total_read > max_bytes:
                        raise TransportError(
                            code="RESPONSE_PAYLOAD_TOO_LARGE",
                            message=(
                                f"La respuesta de Maya superó el límite de seguridad de {max_bytes} bytes."
                            ),
                            recoverable=True,
                            suggestion="Use filtros o paginación para reducir la cantidad de datos devueltos.",
                        )
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break
        except TimeoutError as exc:
            raise TransportError(
                code="MAYA_TIMEOUT",
                message=(
                    f"La operación '{request.action}' excedió el tiempo límite de {timeout_sec:.2f}s en Maya."
                ),
                recoverable=True,
                suggestion="Verifique si Maya está ocupado o en un diálogo modal e intente nuevamente.",
            ) from exc
        except OSError as exc:
            raise TransportError(
                code="MAYA_CONNECTION_ERROR",
                message=(
                    f"No fue posible comunicarse con el puente de Maya en {self._host}:{self._port}."
                ),
                recoverable=True,
                suggestion="Asegúrese de que Maya 2027 esté abierto y que `maya_bridge.bootstrap.start_server()` esté activo.",
            ) from exc

        raw_response = b"".join(chunks)
        return decode_bridge_response(
            raw_response,
            expected_request_id=request.request_id,
            max_payload_bytes=max_bytes,
        )
