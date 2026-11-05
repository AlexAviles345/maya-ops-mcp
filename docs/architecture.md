# Arquitectura de Maya Retopo MCP

## 1. Visión General de Dos Procesos

El sistema está dividido estrictamente en **dos procesos aislados** que se comunican únicamente a través de un socket TCP en `loopback` (`127.0.0.1`) mediante mensajes JSON delimitados por línea (NDJSON) con validación de tamaño y esquema:

```text
+-------------------------------------------------------+
| Cliente MCP (Codex / Agente IA)                       |
+-------------------------------------------------------+
                           |
                           | JSON-RPC 2.0 sobre stdio
                           v
+-------------------------------------------------------+
| Proceso Externo: maya-retopo-mcp (Python 3.11+)       |
|  - Protocolo MCP (stdio)                              |
|  - Validación de esquemas de entrada/salida           |
|  - Políticas de seguridad (Modos, Rutas, Permisos)    |
|  - Envoltura uniforme de respuesta y sanitización     |
|  - NUNCA importa maya.cmds ni maya.api.OpenMaya       |
+-------------------------------------------------------+
                           |
                           | TCP Loopback (127.0.0.1)
                           | Mensajes JSON tipados (sin código libre)
                           v
+-------------------------------------------------------+
| Puente Interno en Maya: maya_bridge (Maya 2027 GUI)   |
|  - Servidor TCP restringido a 127.0.0.1               |
|  - Despacho al hilo principal (executeInMainThread)   |
|  - Registro cerrado de handlers (handlers_read, etc.) |
|  - Consultas y mutaciones con cmds / OpenMaya 2.0     |
+-------------------------------------------------------+
```

## 2. Responsabilidades del Proceso Externo (`src/maya_retopo_mcp`)

1. **Servidor MCP (`server.py`):**
   - Implementa el protocolo MCP sobre `stdio` (JSON-RPC 2.0: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`).
   - Registra las herramientas con metadatos explícitos de seguridad (`readOnlyHint`, `destructiveHint`, `idempotentHint`).
2. **Políticas (`policies/`):**
   - `permissions.py`: Verifica que la herramienta invocada esté permitida en el modo actual (`READ_ONLY`, `PREVIEW`, `APPLY`).
   - `paths.py`: Resuelve rutas reales, bloquea traversal (`..`), rutas UNC (`\\servidor\...`), enlaces simbólicos fuera de `project_root` y protege `original_dir` como solo lectura inmutable.
   - `protected_mesh.py`: Almacena y compara la huella inmutable de la malla `high_poly`.
3. **Transporte (`transport/`):**
   - `protocol.py`: Serialización y deserialización segura con límites de tamaño de payload (`max_payload_bytes`), validación de identificadores de comando y rechazo de ruido o respuestas truncadas.
   - `command_port.py`: Cliente TCP con timeout configurable, reintentos controlados y verificación estricta de que el host sea loopback (`127.0.0.1` o `localhost`).

## 3. Responsabilidades del Puente en Maya (`maya_bridge/`)

1. **Bootstrap (`bootstrap.py`):**
   - Abre un servidor TCP en segundo plano escuchando únicamente en `127.0.0.1`.
   - Canaliza cada solicitud hacia el hilo principal de Maya usando `maya.utils.executeInMainThreadWithResult` cuando se ejecuta dentro de Maya GUI.
2. **Dispatcher (`dispatcher.py`):**
   - Mantiene una tabla estática (`ALLOWED_HANDLERS`) que asocia nombres de acciones (`maya.health`, `scene.describe`, etc.) con funciones Python auditadas.
   - **Prohibición absoluta** de `eval()`, `exec()`, `subprocess`, `os.system` o `maya.mel.eval` con entradas del usuario.
3. **Módulos de Dominio:**
   - `handlers_read.py`, `handlers_preview.py`, `handlers_apply.py`
   - `topology.py`, `symmetry.py`, `viewport.py`, `checkpoint.py`

