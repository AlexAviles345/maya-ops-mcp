"""Servidor MCP (`stdio`) para Maya Retopo MCP (Fase 0 + Fase 1: Solo Lectura)."""

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
from maya_retopo_mcp.policies.paths import ProjectPathsPolicy
from maya_retopo_mcp.policies.permissions import TOOL_SECURITY_REGISTRY
from maya_retopo_mcp.tools.maya_tools import execute_maya_health
from maya_retopo_mcp.tools.project_tools import execute_project_configure
from maya_retopo_mcp.tools.retopo_tools import (
    execute_retopo_analyze_mesh,
    execute_retopo_analyze_symmetry,
    execute_retopo_boundary_loops,
    execute_retopo_detect_candidates,
)
from maya_retopo_mcp.tools.scene_tools import (
    execute_scene_describe,
    execute_scene_list_meshes,
)
from maya_retopo_mcp.tools.selection_tools import execute_selection_get
from maya_retopo_mcp.tools.viewport_tools import execute_viewport_capture
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient

ToolHandler = Callable[[dict[str, Any] | None], ToolResponseEnvelope]

TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "maya.health": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "project.configure": {
        "type": "object",
        "properties": {
            "project_root": {"type": "string"},
            "original_dir": {"type": "string"},
            "output_dir": {"type": "string"},
            "reports_dir": {"type": "string"},
            "backups_dir": {"type": "string"},
        },
        "required": ["project_root", "original_dir", "output_dir", "reports_dir", "backups_dir"],
        "additionalProperties": False,
    },
    "scene.describe": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "scene.list_meshes": {
        "type": "object",
        "properties": {
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            "include_hidden": {"type": "boolean", "default": True},
            "include_intermediate": {"type": "boolean", "default": False},
            "name_contains": {"type": "string", "default": ""},
            "min_faces": {"type": "integer", "minimum": 0, "default": 0},
            "max_faces": {"type": ["integer", "null"], "default": None},
        },
        "additionalProperties": False,
    },
    "selection.get": {
        "type": "object",
        "properties": {
            "max_components": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 500},
        },
        "additionalProperties": False,
    },
    "retopo.detect_candidates": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "retopo.analyze_mesh": {
        "type": "object",
        "properties": {
            "dag_path": {"type": "string"},
            "coincident_tolerance": {"type": "number", "default": 0.0001},
        },
        "required": ["dag_path"],
        "additionalProperties": False,
    },
    "retopo.analyze_symmetry": {
        "type": "object",
        "properties": {
            "dag_path": {"type": "string"},
            "tolerance": {"type": "number", "default": 0.05},
        },
        "required": ["dag_path"],
        "additionalProperties": False,
    },
    "retopo.boundary_loops": {
        "type": "object",
        "properties": {
            "dag_path": {"type": "string"},
        },
        "required": ["dag_path"],
        "additionalProperties": False,
    },
    "viewport.capture": {
        "type": "object",
        "properties": {
            "camera": {"type": "string", "default": "persp"},
            "width": {"type": "integer", "minimum": 64, "maximum": 4096, "default": 1024},
            "height": {"type": "integer", "minimum": 64, "maximum": 4096, "default": 1024},
            "wireframe_on_shaded": {"type": "boolean", "default": True},
            "isolate": {"type": "array", "items": {"type": "string"}, "default": []},
            "frame_selected": {"type": "boolean", "default": True},
            "file_name": {"type": ["string", "null"], "default": None},
        },
        "additionalProperties": False,
    },
}


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
        self.project_policy: ProjectPathsPolicy | None = None
        self._tools: dict[str, tuple[dict[str, Any], ToolHandler]] = {}
        self._register_phase0_and_phase1_tools()

    def _set_project_policy(self, policy: ProjectPathsPolicy) -> None:
        self.project_policy = policy

    def _register_tool(self, tool_name: str, handler: ToolHandler) -> None:
        meta = TOOL_SECURITY_REGISTRY[tool_name]
        schema: dict[str, Any] = {
            "name": meta.name,
            "description": meta.description,
            "inputSchema": TOOL_INPUT_SCHEMAS[tool_name],
            "annotations": meta.to_annotations(),
        }
        self._tools[tool_name] = (schema, handler)

    def _register_phase0_and_phase1_tools(self) -> None:
        self._register_tool(
            "maya.health",
            lambda args: execute_maya_health(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "project.configure",
            lambda args: execute_project_configure(
                config=self.config,
                arguments=args,
                on_policy_configured=self._set_project_policy,
            ),
        )
        self._register_tool(
            "scene.describe",
            lambda args: execute_scene_describe(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "scene.list_meshes",
            lambda args: execute_scene_list_meshes(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "selection.get",
            lambda args: execute_selection_get(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "retopo.detect_candidates",
            lambda args: execute_retopo_detect_candidates(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "retopo.analyze_mesh",
            lambda args: execute_retopo_analyze_mesh(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "retopo.analyze_symmetry",
            lambda args: execute_retopo_analyze_symmetry(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "retopo.boundary_loops",
            lambda args: execute_retopo_boundary_loops(
                config=self.config,
                client=self.client,
                arguments=args,
            ),
        )
        self._register_tool(
            "viewport.capture",
            lambda args: execute_viewport_capture(
                config=self.config,
                client=self.client,
                arguments=args,
                project_policy=self.project_policy,
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
    """Ejecuta una autocomprobación local de Fase 0 y Fase 1 usando el puente Maya simulado en loopback."""
    from maya_bridge.bootstrap import MayaBridgeServer

    bridge = MayaBridgeServer(host="127.0.0.1", port=0)
    status = bridge.start()
    try:
        cfg = ServerConfig(maya_host="127.0.0.1", maya_port=int(status["port"]))
        server = MayaRetopoMcpServer(config=cfg)
        health_env = server.call_tool("maya.health", {})
        candidates_env = server.call_tool("retopo.detect_candidates", {})
        symmetry_env = server.call_tool("retopo.analyze_symmetry", {"dag_path": "|retopo_cuerpo"})
        summary = {
            "health_ok": health_env.ok,
            "registered_tools_count": len(server.list_tools()),
            "candidates_ok": candidates_env.ok,
            "symmetry_ok": symmetry_env.ok,
            "recommended_axis": symmetry_env.data.get("recommended_axis"),
            "plane_offset": symmetry_env.data.get("plane_offset"),
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if (health_env.ok and candidates_env.ok and symmetry_env.ok) else 1
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
