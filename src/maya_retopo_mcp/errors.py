"""Definiciones de errores tipados y estructurados para Maya Retopo MCP."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TRACEBACK_LINE_RE = re.compile(r"^\s*(?:Traceback \(most recent call last\):|File \".*\", line \d+)", re.MULTILINE)
_WINDOWS_USER_PATH_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+[\\/]+[^\s\"']*", re.IGNORECASE)


def sanitize_error_message(message: str, *, max_length: int = 400) -> str:
    """
    Elimina trazas de pila (stack traces), rutas locales del perfil de usuario
    y caracteres de control antes de devolver un mensaje de error al cliente MCP.
    """
    if not message:
        return "Error en la operación solicitada."
    # Cortar en caso de que incluya un bloque Traceback
    tb_match = _TRACEBACK_LINE_RE.search(message)
    cleaned = message[: tb_match.start()].strip() if tb_match else message.strip()
    if not cleaned:
        cleaned = "Error interno procesando la operación."
    # Redactar rutas de perfil de usuario de Windows
    cleaned = _WINDOWS_USER_PATH_RE.sub("<ruta_local_redactada>", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3] + "..."
    return cleaned


@dataclass(frozen=True)
class ErrorDetail:
    """Estructura serializable de error según el contrato común de respuesta (Sección 7)."""

    code: str
    message: str
    recoverable: bool = True
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": sanitize_error_message(self.message),
            "recoverable": self.recoverable,
            "suggestion": self.suggestion,
        }


class MayaRetopoMcpError(Exception):
    """Excepción base del servidor MCP con metadatos seguros para el cliente."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        suggestion: str = "",
    ) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(
            code=code,
            message=message,
            recoverable=recoverable,
            suggestion=suggestion,
        )


class SecurityPolicyError(MayaRetopoMcpError):
    """Violación de política de seguridad (rutas, modo, loopback, operaciones prohibidas)."""


class TransportError(MayaRetopoMcpError):
    """Error de transporte hacia el puente en Maya (conexión, timeout, respuesta truncada)."""


class ValidationError(MayaRetopoMcpError):
    """Error de validación de argumentos de entrada o estado de topología/malla."""


class HighPolyChangedError(SecurityPolicyError):
    """La malla high-poly protegida sufrió cambios durante una operación."""

    def __init__(
        self,
        message: str = "La escultura protegida cambio durante la operacion.",
        suggestion: str = "Restaure el checkpoint y revise el handler regional.",
    ) -> None:
        super().__init__(
            code="HIGH_POLY_CHANGED",
            message=message,
            recoverable=True,
            suggestion=suggestion,
        )

