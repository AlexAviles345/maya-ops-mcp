"""Pruebas de integración de transporte loopback, `maya.health` y resiliencia ante fallos."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from typing import Any
from unittest.mock import patch

from maya_bridge.bootstrap import MayaBridgeServer
from maya_bridge.dispatcher import BridgeDispatcher
from maya_bridge.handlers_preview import maya_undo_chunk
from maya_retopo_mcp.config import ServerConfig, ServerMode
from maya_retopo_mcp.errors import TransportError
from maya_retopo_mcp.server import MayaRetopoMcpServer
from maya_retopo_mcp.transport.command_port import MayaLoopbackClient
from maya_retopo_mcp.transport.protocol import decode_bridge_response


class TestFakeMayaTransportAndHealth(unittest.TestCase):
    def test_maya_health_end_to_end_and_mcp_jsonrpc(self) -> None:
        bridge = MayaBridgeServer(host="127.0.0.1", port=0)
        status = bridge.start()
        try:
            cfg = ServerConfig(
                maya_host="127.0.0.1",
                maya_port=int(status["port"]),
                mode=ServerMode.READ_ONLY,
            )
            mcp = MayaRetopoMcpServer(config=cfg)

            # 1. initialize
            init_resp = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            self.assertIsNotNone(init_resp)
            assert init_resp is not None
            self.assertEqual(init_resp["result"]["serverInfo"]["name"], "maya-retopo-mcp")

            # 2. tools/list
            list_resp = mcp.handle_jsonrpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert list_resp is not None
            tools = list_resp["result"]["tools"]
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0]["name"], "maya.health")
            self.assertTrue(tools[0]["annotations"]["readOnlyHint"])

            # 3. tools/call -> maya.health
            call_resp = mcp.handle_jsonrpc_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "maya.health", "arguments": {}},
                }
            )
            assert call_resp is not None
            self.assertFalse(call_resp["result"]["isError"])
            structured = call_resp["result"]["structuredContent"]
            self.assertTrue(structured["ok"])
            self.assertEqual(structured["tool"], "maya.health")
            self.assertEqual(structured["data"]["maya_version"], "2027")
            self.assertEqual(structured["data"]["mode"], "READ_ONLY")
            self.assertFalse(structured["data"]["modified"])
        finally:
            bridge.stop()

    def test_connection_failure_and_reconnection(self) -> None:
        # Iniciar y detener inmediatamente para obtener un puerto libre donde no escucha nadie
        bridge = MayaBridgeServer(host="127.0.0.1", port=0)
        port = int(bridge.start()["port"])
        bridge.stop()

        cfg = ServerConfig(maya_host="127.0.0.1", maya_port=port, timeout_sec=0.5)
        mcp = MayaRetopoMcpServer(config=cfg)

        # Cuando Maya está cerrado devuelve error estructurado recuperable
        fail_env = mcp.call_tool("maya.health", {})
        self.assertFalse(fail_env.ok)
        assert fail_env.error is not None
        self.assertEqual(fail_env.error.code, "MAYA_CONNECTION_ERROR")
        self.assertTrue(fail_env.error.recoverable)

        # Al volver a levantar Maya en el mismo puerto, se reconecta sin reiniciar el MCP
        bridge_restarted = MayaBridgeServer(host="127.0.0.1", port=port)
        bridge_restarted.start()
        try:
            ok_env = mcp.call_tool("maya.health", {})
            self.assertTrue(ok_env.ok)
            self.assertEqual(ok_env.data["maya_version"], "2027")
        finally:
            bridge_restarted.stop()

    def test_truncated_and_noisy_responses(self) -> None:
        # 1. Ruido previo de Maya seguido de JSON válido en la última línea debe decodificarse
        noisy_bytes = (
            b"mental ray: info: startup...\n"
            b'Warning: file: some.mel line 12\n'
            b'{"request_id":"req123","ok":true,"data":{"ok":true,"maya_version":"2027"}}\n'
        )
        decoded = decode_bridge_response(noisy_bytes, expected_request_id="req123")
        self.assertTrue(decoded.ok)
        self.assertEqual(decoded.data["maya_version"], "2027")

        # 2. JSON truncado debe rechazarse con INVALID_BRIDGE_RESPONSE
        truncated_bytes = b'{"request_id":"req123","ok":true,"data":{"maya_ver'
        with self.assertRaises(TransportError) as ctx:
            decode_bridge_response(truncated_bytes, expected_request_id="req123")
        self.assertEqual(ctx.exception.detail.code, "INVALID_BRIDGE_RESPONSE")

    def test_maya_busy_returns_structured_busy_code(self) -> None:
        barrier = threading.Event()
        release = threading.Event()

        def slow_handler(params: dict[str, Any]) -> dict[str, Any]:
            _ = params
            barrier.set()
            release.wait(timeout=2.0)
            return {
                "ok": True,
                "maya_version": "2027",
                "python_version": "3.11",
                "scene": None,
                "modified": False,
            }

        dispatcher = BridgeDispatcher(handlers={"maya.health": slow_handler})
        bridge = MayaBridgeServer(host="127.0.0.1", port=0, dispatcher=dispatcher)
        port = int(bridge.start()["port"])
        try:
            cfg = ServerConfig(maya_host="127.0.0.1", maya_port=port, timeout_sec=3.0)
            client = MayaLoopbackClient(cfg, max_retries=0)

            first_result: list[Any] = []
            t1 = threading.Thread(
                target=lambda: first_result.append(client.send_action("maya.health", {})),
                daemon=True,
            )
            t1.start()
            self.assertTrue(barrier.wait(timeout=1.5))

            # Segunda llamada concurrente recibe MAYA_BUSY inmediatamente
            second_resp = client.send_action("maya.health", {})
            self.assertFalse(second_resp.ok)
            assert second_resp.error is not None
            self.assertEqual(second_resp.error.code, "MAYA_BUSY")

            release.set()
            t1.join(timeout=2.0)
            self.assertTrue(first_result[0].ok)
        finally:
            release.set()
            bridge.stop()

    def test_operation_timeout_raises_maya_timeout(self) -> None:
        # Servidor TCP raw que acepta la conexión pero no responde a tiempo
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def slow_accept() -> None:
            conn, _ = srv.accept()
            time.sleep(0.5)
            conn.close()

        t = threading.Thread(target=slow_accept, daemon=True)
        t.start()
        try:
            cfg = ServerConfig(maya_host="127.0.0.1", maya_port=port, timeout_sec=0.15)
            mcp = MayaRetopoMcpServer(config=cfg)
            env = mcp.call_tool("maya.health", {})
            self.assertFalse(env.ok)
            assert env.error is not None
            self.assertEqual(env.error.code, "MAYA_TIMEOUT")
        finally:
            srv.close()
            t.join(timeout=1.0)

    def test_partial_error_triggers_automatic_undo_rollback(self) -> None:
        """Simula `maya.cmds` con un fallo a mitad de una mutación y verifica que se hace undo."""
        scene_vertices = [0.0, 0.0, 0.0]
        undo_stack: list[list[float]] = []
        calls: list[str] = []

        class FakeCmds:
            @staticmethod
            def undoInfo(**kwargs: Any) -> None:
                if kwargs.get("openChunk"):
                    calls.append("openChunk")
                    undo_stack.append(list(scene_vertices))
                elif kwargs.get("closeChunk"):
                    calls.append("closeChunk")

            @staticmethod
            def undo() -> None:
                calls.append("undo")
                if undo_stack:
                    restored = undo_stack.pop()
                    scene_vertices[:] = restored

        with patch("maya_bridge.handlers_preview._get_maya_cmds", return_value=FakeCmds):
            with self.assertRaises(RuntimeError):
                with maya_undo_chunk("test_region_op", always_undo=False):
                    # Mutación parcial seguida de excepción
                    scene_vertices[0] = 999.0
                    raise RuntimeError("Fallo parcial simulado a mitad de la región")

        # El estado volvió exactamente a [0.0, 0.0, 0.0] y se invocó openChunk -> closeChunk -> undo
        self.assertEqual(scene_vertices, [0.0, 0.0, 0.0])
        self.assertEqual(calls, ["openChunk", "closeChunk", "undo"])


if __name__ == "__main__":
    unittest.main()

