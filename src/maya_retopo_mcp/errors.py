"""Definiciones de errores tipados y estructurados para Maya Retopo MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
            "message": self.message,
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

