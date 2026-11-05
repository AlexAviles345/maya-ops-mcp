# Configuración de Autodesk Maya 2027 (`maya_setup`)

## 1. Principio de Conexión Segura

`maya-retopo-mcp` no utiliza un `commandPort` estándar abierto a ejecución libre de MEL/Python. En su lugar, utiliza el módulo local `maya_bridge`, que levanta un listener TCP exclusivo en `127.0.0.1` y despacha únicamente acciones JSON registradas hacia el hilo principal de Maya.

---

## 2. Iniciar el Puente Manualmente en Maya GUI

Abre **Autodesk Maya 2027**, abre el **Script Editor** en una pestaña **Python** y ejecuta:

```python
import sys

REPO_ROOT = r"C:/Users/CDS/Documents/Repositorios/maya-ops-mcp"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from maya_bridge import bootstrap

server_info = bootstrap.start_server(host="127.0.0.1", port=7001)
print("Maya Retopo Bridge activo:", server_info)
```

---

## 3. Comprobar o Detener el Puente en Maya

Para verificar el estado dentro de Maya:

```python
from maya_bridge import bootstrap
print(bootstrap.get_server_status())
```

Para detener el servidor limpiamente (por ejemplo, al cambiar de proyecto o realizar un rollback):

```python
from maya_bridge import bootstrap
bootstrap.stop_server()
```

---

## 4. Variables de Entorno del Servidor MCP

El proceso externo (`maya_retopo_mcp.server`) acepta las siguientes variables de entorno:

| Variable | Valor por Defecto | Descripción |
| :--- | :--- | :--- |
| `MAYA_MCP_HOST` | `127.0.0.1` | Dirección del puente Maya (solo se permite `127.0.0.1` o `localhost`). |
| `MAYA_MCP_PORT` | `7001` | Puerto TCP local donde escucha `maya_bridge`. |
| `MAYA_MCP_TIMEOUT_SEC` | `15.0` | Tiempo máximo de espera por solicitud hacia Maya en segundos. |
| `MAYA_MCP_MAX_PAYLOAD_BYTES` | `1048576` | Tamaño máximo de respuesta JSON permitido (1 MiB por defecto). |
| `MAYA_MCP_MODE` | `READ_ONLY` | Modo operativo inicial (`READ_ONLY`, `PREVIEW`, `APPLY`). |
| `MAYA_MCP_LOG_FILE` | *(opcional)* | Ruta local para almacenar logs JSON estructurados. |

