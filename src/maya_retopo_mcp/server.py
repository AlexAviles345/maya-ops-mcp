"""Servidor MCP (`stdio`) para Maya Retopo MCP (Fase 0: Base Segura y `maya.health`)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from maya_retopo_mcp import __version__
from maya_retopo_mcp.config import ServerConfig
from maya_retopo_mcp.errors import ErrorDetail
from maya_retopo_mcp.logging_config import configure_logging
from maya_retopo_mcp.models.responses import ToolResponseEnvelope
from maya_retopo_mcp.policies.permissions import TOOL_SECURITY_REGISTRY
from maya_retopo_mcp.tools.maya_tools import execute_maya_health
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient

ToolHandler = Callable[[dict[str, Any] | None], ToolResponseEnvelope]


class MayaRetopoMcpServer:
    """Servidor Model Context Protocol sobre `stdio` para Autodesk Maya."""

    def __init__(
        self,
        config: ServerConfig | None = None,
        client: MayaLoopbackClient | None = None,
    ) -> None:
        self.config = config or ServerConfig.from_env()
        self.logger = configure_logging(log_file=self.config.log_file)
        self.client = client or MayaLoopbackClient(self.config)
        self._tools: dict[str, tuple[dict[str, Any], ToolHandler]] = {}
        self._register_phase0_tools()

    def _register_phase0_tools(self) -> None:
        meta = TOOL_SECURITY_REGISTRY["maya.health"]
        schema: dict[str, Any] = {
            "name": meta.name,
            "description": meta.description,
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "annotations": meta.to_annotations(),
        }
        self._tools[meta.name] = (
            schema,
            lambda args: execute_maya_health(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """Devuelve la lista de herramientas MCP activas con sus esquemas tipados."""
        return [entry[0] for entry in self._tools.values()]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResponseEnvelope:
        """Invoca una herramienta MCP por nombre y devuelve su `ToolResponseEnvelope`."""
        entry = self._tools.get(name)
        if entry is None:
            return ToolResponseEnvelope.failure(
                tool=name,
                error=ErrorDetail(
                    code="UNKNOWN_TOOL",
                    message=f"La herramienta '{name}' no está disponible en la fase actual.",
                    recoverable=False,
                    suggestion="Use `tools/list` para consultar las herramientas habilitadas.",
                ),
            )
        _, handler = entry
        return handler(arguments)

    def handle_jsonrpc_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Procesa un mensaje JSON-RPC 2.0 del protocolo MCP y devuelve la respuesta."""
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        # Las notificaciones (sin id) no devuelven respuesta por stdout
        if msg_id is None:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "maya-retopo-mcp",
                        "version": __version__,
                    },
                },
            }

        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {},
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": self.list_tools(),
                },
            }

        if method == "tools/call":
            tool_name = str(params.get("name", ""))
            arguments = params.get("arguments")
            if arguments is not None and not isinstance(arguments, dict):
                envelope = ToolResponseEnvelope.failure(
                    tool=tool_name,
                    error=ErrorDetail(
                        code="INVALID_ARGUMENTS",
                        message="El campo 'arguments' debe ser un objeto JSON.",
                        recoverable=True,
                        suggestion="Envíe un objeto JSON `{}` como argumentos.",
                    ),
                )
            else:
                envelope = self.call_tool(tool_name, arguments)

            envelope_dict = envelope.to_dict()
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(envelope_dict, ensure_ascii=False),
                        }
                    ],
                    "structuredContent": envelope_dict,
                    "isError": not envelope.ok,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Método MCP no soportado: '{method}'.",
            },
        }

    def serve_stdio(self) -> None:
        """Bucle principal MCP leyendo JSON-RPC por línea desde `stdin` y escribiendo a `stdout`."""
        self.logger.info(
            "Maya Retopo MCP iniciado en modo %s apuntando a %s:%d",
            self.config.mode.value,
            self.config.maya_host,
            self.config.maya_port,
        )
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    continue
                response = self.handle_jsonrpc_message(msg)
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error: JSON inválido."},
                }
                sys.stdout.write(json.dumps(err_resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def run_self_check() -> int:
    """Ejecuta una autocomprobación local de Fase 0 usando un puente Maya simulado en loopback."""
    from maya_bridge.bootstrap import MayaBridgeServer

    bridge = MayaBridgeServer(host="127.0.0.1", port=0)
    status = bridge.start()
    try:
        cfg = ServerConfig(maya_host="127.0.0.1", maya_port=int(status["port"]))
        server = MayaRetopoMcpServer(config=cfg)
        envelope = server.call_tool("maya.health", {})
        print(json.dumps(envelope.to_dict(), indent=2, ensure_ascii=False))
        return 0 if envelope.ok else 1
    finally:
        bridge.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Servidor Maya Retopo MCP (stdio)")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Ejecuta una prueba rápida de extremo a extremo en loopback con puente simulado y termina.",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        return run_self_check()

    server = MayaRetopoMcpServer()
    server.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
