"""Bootstrap del servidor TCP loopback dentro de Autodesk Maya (`maya_bridge`)."""

from __future__ import annotations

import socketserver
import threading
from typing import Any

from maya_bridge.dispatcher import BridgeDispatcher

ALLOWED_BIND_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class MayaBridgeServer:
    """Servidor TCP local para escuchar solicitudes de `maya-retopo-mcp` en loopback."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7001,
        dispatcher: BridgeDispatcher | None = None,
    ) -> None:
        normalized = host.strip().lower()
        if normalized not in ALLOWED_BIND_HOSTS:
            raise ValueError(
                f"El puente de Maya solo puede enlazarse a loopback (127.0.0.1 o localhost), recibido: '{host}'."
            )
        self._host = "127.0.0.1" if normalized == "localhost" else normalized
        self._requested_port = int(port)
        self._dispatcher = dispatcher or BridgeDispatcher()
        self._tcp_server: _ThreadedTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        if self._tcp_server is not None:
            return int(self._tcp_server.server_address[1])
        return self._requested_port

    @property
    def dispatcher(self) -> BridgeDispatcher:
        return self._dispatcher

    def start(self) -> dict[str, Any]:
        """Inicia el servidor TCP en un hilo daemon si no está activo."""
        if self._tcp_server is not None:
            return self.status()

        dispatcher_ref = self._dispatcher

        class _RequestHandler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                raw_line = self.rfile.readline(1_048_576)
                if not raw_line:
                    return
                response_bytes = dispatcher_ref.dispatch_raw(raw_line)
                self.wfile.write(response_bytes)
                self.wfile.flush()

        self._tcp_server = _ThreadedTCPServer((self._host, self._requested_port), _RequestHandler)
        self._thread = threading.Thread(
            target=self._tcp_server.serve_forever,
            name="MayaRetopoBridgeThread",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def stop(self) -> None:
        """Detiene el servidor TCP y libera el puerto."""
        if self._tcp_server is not None:
            self._tcp_server.shutdown()
            self._tcp_server.server_close()
            self._tcp_server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def status(self) -> dict[str, Any]:
        return {
            "running": self._tcp_server is not None,
            "host": self._host,
            "port": self.port,
        }


_GLOBAL_SERVER: MayaBridgeServer | None = None


def start_server(host: str = "127.0.0.1", port: int = 7001) -> dict[str, Any]:
    """Inicia la instancia global del puente dentro de Maya."""
    global _GLOBAL_SERVER
    if _GLOBAL_SERVER is not None:
        _GLOBAL_SERVER.stop()
    _GLOBAL_SERVER = MayaBridgeServer(host=host, port=port)
    return _GLOBAL_SERVER.start()


def stop_server() -> dict[str, Any]:
    """Detiene la instancia global del puente dentro de Maya."""
    global _GLOBAL_SERVER
    if _GLOBAL_SERVER is not None:
        _GLOBAL_SERVER.stop()
        _GLOBAL_SERVER = None
    return {"running": False}


def get_server_status() -> dict[str, Any]:
    """Devuelve el estado actual de la instancia global del puente."""
    if _GLOBAL_SERVER is None:
        return {"running": False, "host": "127.0.0.1", "port": None}
    return _GLOBAL_SERVER.status()

