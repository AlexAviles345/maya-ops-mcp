"""Configuración tipada y modos del servidor Maya Retopo MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from maya_retopo_mcp.errors import SecurityPolicyError

ALLOWED_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost"})


class ServerMode(str, Enum):
    """Modos de seguridad configurables del servidor (Sección 5)."""

    READ_ONLY = "READ_ONLY"
    PREVIEW = "PREVIEW"
    APPLY = "APPLY"


def validate_loopback_host(host: str) -> str:
    """Garantiza que toda comunicación con Maya permanezca estrictamente en loopback."""
    normalized = host.strip().lower()
    if normalized not in ALLOWED_LOOPBACK_HOSTS:
        raise SecurityPolicyError(
            code="NON_LOOPBACK_FORBIDDEN",
            message=f"El host '{host}' no está permitido. Solo se admite loopback (127.0.0.1 o localhost).",
            recoverable=False,
            suggestion="Configure MAYA_MCP_HOST en '127.0.0.1'.",
        )
    return normalized


@dataclass
class ServerConfig:
    """Configuración de tiempo de ejecución del servidor MCP."""

    maya_host: str = "127.0.0.1"
    maya_port: int = 7001
    timeout_sec: float = 15.0
    max_payload_bytes: int = 1_048_576  # 1 MiB
    mode: ServerMode = ServerMode.READ_ONLY
    log_file: str | None = None

    def __post_init__(self) -> None:
        self.maya_host = validate_loopback_host(self.maya_host)
        if not (1024 <= self.maya_port <= 65535):
            raise SecurityPolicyError(
                code="INVALID_PORT",
                message=f"El puerto {self.maya_port} debe estar en el rango 1024..65535.",
                recoverable=False,
                suggestion="Use un puerto local no privilegiado, por ejemplo 7001.",
            )
        if self.timeout_sec <= 0 or self.timeout_sec > 300:
            raise SecurityPolicyError(
                code="INVALID_TIMEOUT",
                message=f"El timeout ({self.timeout_sec}s) debe estar entre 0.1 y 300 segundos.",
                recoverable=False,
                suggestion="Ajuste MAYA_MCP_TIMEOUT_SEC a un valor razonable (ej. 15.0).",
            )
        if self.max_payload_bytes < 1024 or self.max_payload_bytes > 50_000_000:
            raise SecurityPolicyError(
                code="INVALID_MAX_PAYLOAD",
                message="El límite de payload debe estar entre 1 KiB y 50 MiB.",
                recoverable=False,
                suggestion="Ajuste MAYA_MCP_MAX_PAYLOAD_BYTES (por defecto 1048576).",
            )
        if not isinstance(self.mode, ServerMode):
            self.mode = ServerMode(str(self.mode).upper())

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Construye la configuración desde variables de entorno, forzando READ_ONLY si no se especifica."""
        host = os.environ.get("MAYA_MCP_HOST", "127.0.0.1")
        port = int(os.environ.get("MAYA_MCP_PORT", "7001"))
        timeout = float(os.environ.get("MAYA_MCP_TIMEOUT_SEC", "15.0"))
        max_bytes = int(os.environ.get("MAYA_MCP_MAX_PAYLOAD_BYTES", "1048576"))
        raw_mode = os.environ.get("MAYA_MCP_MODE", "READ_ONLY").strip().upper()
        try:
            mode = ServerMode(raw_mode)
        except ValueError as exc:
            raise SecurityPolicyError(
                code="INVALID_SERVER_MODE",
                message=f"Modo de servidor inválido: '{raw_mode}'.",
                recoverable=False,
                suggestion="Use READ_ONLY, PREVIEW o APPLY.",
            ) from exc
        log_file = os.environ.get("MAYA_MCP_LOG_FILE") or None
        return cls(
            maya_host=host,
            maya_port=port,
            timeout_sec=timeout,
            max_payload_bytes=max_bytes,
            mode=mode,
            log_file=log_file,
        )

