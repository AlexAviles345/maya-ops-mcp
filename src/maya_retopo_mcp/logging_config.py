"""Configuración de logging estructurado y sanitizado (nunca contamina stdout de MCP)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonStderrFormatter(logging.Formatter):
    """Formateador JSON de una línea para logs locales de auditoría y diagnóstico."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "tool"):
            payload["tool"] = getattr(record, "tool")
        if hasattr(record, "error_code"):
            payload["error_code"] = getattr(record, "error_code")
        if record.exc_info:
            payload["exc_type"] = (
                record.exc_info[0].__name__ if record.exc_info[0] is not None else "Exception"
            )
            payload["traceback"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(log_file: str | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configura el logger raíz de `maya_retopo_mcp` escribiendo en stderr y archivo opcional."""
    logger = logging.getLogger("maya_retopo_mcp")
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = JsonStderrFormatter()

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    if log_file:
        path = Path(log_file).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
