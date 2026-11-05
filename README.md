# Maya Retopo MCP (`maya-retopo-mcp`)

Servidor **Model Context Protocol (MCP)** local diseñado para permitir que agentes de IA inspeccionen y asistan flujos de trabajo de **retopología en Autodesk Maya 2027** de forma **segura, visual, reversible y verificable**.

> **Filosofía central:** *Inspeccionar → Previsualizar → Aprobar → Ejecutar → Verificar → Poder revertir.*

---

## Características Principales

- **100 % Local y Loopback:** Toda comunicación entre el proceso MCP y Autodesk Maya ocurre exclusivamente en `127.0.0.1` (`localhost`). Sin acceso a red externa ni servicios en la nube.
- **Modo `READ_ONLY` por defecto:** El servidor arranca siempre en modo de solo lectura. Ninguna herramienta de lectura modifica la escena ni altera el flag `modified` de Maya.
- **Sin ejecución arbitraria de código:** No expone `eval`, `exec`, MEL arbitrario ni comandos de shell. Solo despacha operaciones registradas y auditadas con esquemas tipados.
- **Protección de escultura High-Poly y carpeta `original/`:** Verifica huellas estructurales (UUID, DAG path, conteos V/E/F, bounding box y hash topológico) antes y después de cualquier operación y bloquea cualquier escritura en `original/`.
- **Preview con Undo automático y Checkpoints:** Toda operación regional se prueba en un *undo chunk* aislado, captura evidencia visual del viewport y revierte cambios automáticamente antes de solicitar aplicación explícita.

---

## Estructura del Repositorio

```text
maya-retopo-mcp/
├── README.md                  # Introducción general, instalación y arranque rápido
├── LICENSE                    # Licencia MIT
├── pyproject.toml             # Configuración del paquete Python y herramientas de calidad
├── src/
│   └── maya_retopo_mcp/       # Servidor MCP externo (proceso host)
│       ├── server.py          # Punto de entrada MCP por stdio
│       ├── config.py          # Configuración tipada, modos y límites
│       ├── errors.py          # Catálogo de errores estructurados sin filtración de stack traces
│       ├── logging_config.py  # Logging local sanitizado en JSON
│       ├── transport/         # Cliente TCP loopback y protocolo JSON hacia Maya
│       ├── tools/             # Herramientas MCP separadas por dominio (maya, project, scene, etc.)
│       ├── policies/          # Políticas de rutas, permisos por modo y huella de malla protegida
│       └── models/            # Contratos de entrada/salida y envoltura común de respuestas
├── maya_bridge/               # Puente ejecutado dentro de Autodesk Maya
│   ├── bootstrap.py           # Inicialización del servidor loopback en Maya (hilo principal seguro)
│   ├── dispatcher.py          # Despachador estricto de handlers permitidos (sin eval/exec libre)
│   ├── handlers_read.py       # Handlers de inspección de solo lectura
│   ├── handlers_preview.py    # Handlers de previsualización con undo chunk obligatorio
│   ├── handlers_apply.py      # Handlers de aplicación con checkpoint y validación
│   ├── topology.py            # Análisis determinista de topología (quads, n-gons, fronteras)
│   ├── symmetry.py            # Detección de plano anatómico de simetría
│   ├── viewport.py            # Captura y restauración de estado del viewport
│   └── checkpoint.py          # Gestión de copias recuperables
├── operations/                # Operaciones regionales auditadas (feet_v1, hands_v1, head_face_v1)
├── tests/                     # Suite de pruebas (unit, integration_fake_maya, integration_mayapy, manual_gui)
├── docs/                      # Documentación técnica especializada
└── examples/                  # Ejemplos de configuración para clientes MCP (Codex) y proyectos
```

---

## Requisitos Previos

- **Sistema Operativo:** Windows 10 / 11 (64-bit).
- **Python (Host):** Python `3.11` o superior.
- **Autodesk Maya:** Maya 2027 (para integración GUI o `mayapy` en pruebas de integración).
- **Dependencias externas:** El núcleo de Fase 0 utiliza exclusivamente la biblioteca estándar de Python para minimizar la superficie de ataque y permitir ejecución inmediata sin dependencias de terceros.

---

## Instalación y Arranque Inicial

### 1. Clonar y verificar el entorno

Desde la raíz del repositorio en PowerShell:

```powershell
# Verificar versión de Python
py --version

# Ejecutar el servidor en modo de verificación de salud (o vía cliente MCP stdio)
$env:PYTHONPATH = "src;."
py -m maya_retopo_mcp.server --self-check
```

*(Opcional)* Si deseas instalar el paquete en modo editable dentro de un entorno virtual:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --no-build-isolation --no-deps -e .
```

### 2. Iniciar el Puente en Autodesk Maya (`maya_bridge`)

Dentro del **Script Editor (pestaña Python)** de Autodesk Maya 2027, registra y levanta el puente local en loopback (`127.0.0.1:7001`):

```python
import sys
repo_path = r"C:/Users/CDS/Documents/Repositorios/maya-ops-mcp"
if repo_path not in sys.path:
    sys.path.insert(0, repo_path)

from maya_bridge import bootstrap
bootstrap.start_server(host="127.0.0.1", port=7001)
```

> Consulta [`docs/maya_setup.md`](docs/maya_setup.md) para más detalles sobre cómo configurar el arranque seguro y cómo detener el puente (`bootstrap.stop_server()`).

### 3. Configurar el Cliente MCP (Codex / Claude / Cliente stdio)

Ejemplo de configuración en `codex_config.toml` (ver [`examples/codex_config.toml`](examples/codex_config.toml)):

```toml
[mcp_servers.maya_retopo]
command = "py"
args = ["-m", "maya_retopo_mcp.server"]
env = { PYTHONPATH = "src;.", MAYA_MCP_HOST = "127.0.0.1", MAYA_MCP_PORT = "7001" }
tool_timeout_sec = 120
```

### 4. Ejecutar las Pruebas

Puedes ejecutar toda la batería de pruebas unitarias y de integración con Maya simulado usando `unittest` (incluido en Python) o `pytest`:

```powershell
$env:PYTHONPATH = "src;."
py -m unittest discover -s tests -p "test_*.py" -v
```

---

## Estado por Fases de Implementación

- [x] **Fase 0: Base segura** — Estructura del repositorio, configuración, logging sanitizado, políticas de seguridad base, transporte TCP loopback hacia Maya, puente `maya_bridge`, herramienta `maya.health` y pruebas unitarias + Maya simulado.
- [x] **Fase 1: Solo lectura** — `project.configure`, `scene.describe`, `scene.list_meshes`, `selection.get`, `retopo.detect_candidates`, `retopo.analyze_mesh`, `retopo.analyze_symmetry`, `retopo.boundary_loops`, `viewport.capture`.
- [x] **Fase 2: Selección y roles** — `selection.set`, `retopo.confirm_roles`, huella y protección de malla high-poly.
- [x] **Fase 3: Preview seguro** — Operaciones registradas, undo chunks, `safety.checkpoint`, `retopo.preview_region`.
- [x] **Fase 4: Aplicación** — `retopo.apply_region`, `retopo.validate`, `scene.save_version`.
- [ ] **Fase 5: Endurecimiento** — Límites estrictos, paginación avanzada, auditoría de escenas corruptas y guía de recuperación.

---

## Documentación Especializada (`docs/`)

Para detalles arquitectónicos, modelo de amenazas y referencia de herramientas, consulta la carpeta [`docs/`](docs/):

- [`docs/specification.md`](docs/specification.md) — Especificación íntegra de requisitos del proyecto Maya Retopo MCP.
- [`docs/architecture.md`](docs/architecture.md) — Arquitectura de dos procesos (Host MCP ↔ Puente Maya), protocolo JSON loopback y flujo de datos.
- [`docs/security.md`](docs/security.md) — Modelo de seguridad, esquema de amenazas (*Threat Model*), modos de operación (`READ_ONLY`, `PREVIEW`, `APPLY`) y protección de rutas/mallas.
- [`docs/tool_reference.md`](docs/tool_reference.md) — Referencia detallada de herramientas MCP, contratos de entrada/salida y códigos de error.
- [`docs/maya_setup.md`](docs/maya_setup.md) — Configuración paso a paso de Autodesk Maya 2027, puertos loopback y resolución de problemas.
- [`docs/development.md`](docs/development.md) — Guía de desarrollo, convenciones de código, pruebas con Maya simulado y procedimiento de rollback.

