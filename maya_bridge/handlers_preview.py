"""Handlers de previsualización (`PREVIEW`) con undo chunk y rollback obligatorio."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from maya_bridge.handlers_read import _get_maya_cmds


@contextmanager
def maya_undo_chunk(chunk_name: str, *, always_undo: bool = True) -> Iterator[None]:
    """
    Ejecuta un bloque dentro de un undo chunk de Maya.
    Si `always_undo=True` (modo PREVIEW) o si ocurre una excepción, revierte automáticamente.
    """
    cmds = _get_maya_cmds()
    failed = False
    if cmds is not None:
        cmds.undoInfo(openChunk=True, chunkName=chunk_name)
    try:
        yield
    except Exception:
        failed = True
        raise
    finally:
        if cmds is not None:
            cmds.undoInfo(closeChunk=True)
            if always_undo or failed:
                try:
                    cmds.undo()
                except Exception:
                    pass


def execute_with_rollback_on_error(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Ejecuta `fn` dentro de un undo chunk que hace undo automático si ocurre un error."""
    with maya_undo_chunk("maya_retopo_mcp_op", always_undo=False):
        return fn(*args, **kwargs)
