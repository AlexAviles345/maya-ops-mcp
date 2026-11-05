# Referencia de Herramientas MCP (`tool_reference`)

Todas las herramientas publicadas por `maya-retopo-mcp` siguen el formato `namespace.action` y devuelven la **envoltura uniforme de respuesta** definida en la sección 7 de la especificación.

---

## Envoltura Común de Respuesta

### Éxito (`ok: true`)

```json
{
  "ok": true,
  "tool": "maya.health",
  "timestamp": "2026-11-04T18:45:00-06:00",
  "scene": "C:/proyecto/output/escena_v001.mb",
  "scene_modified": false,
  "data": {},
  "warnings": [],
  "errors": [],
  "duration_ms": 12
}
```

### Error (`ok: false`)

```json
{
  "ok": false,
  "tool": "maya.health",
  "timestamp": "2026-11-04T18:45:00-06:00",
  "scene": null,
  "scene_modified": false,
  "error": {
    "code": "MAYA_CONNECTION_ERROR",
    "message": "No fue posible conectar con el puente de Maya en 127.0.0.1:7001.",
    "recoverable": true,
    "suggestion": "Verifique que Maya 2027 esté abierto y que maya_bridge.bootstrap.start_server() esté activo."
  },
  "duration_ms": 502
}
```

---

## Catálogo de Herramientas por Fase

### Fase 0: Base Segura

#### `maya.health`
- **Modo mínimo requerido:** `READ_ONLY`
- **Clasificación:** Lectura (`read_only=True`, `idempotent=True`, `destructive=False`)
- **Descripción:** Comprueba la conectividad TCP loopback con Maya, versión de Maya y Python, escena actual, estado `modified` y modo activo del servidor MCP.
- **Entrada:** `{}`
- **Salida (`data`):**
  ```json
  {
    "ok": true,
    "maya_version": "2027",
    "python_version": "3.11.x",
    "scene": "C:/proyecto/output/escena.mb",
    "modified": false,
    "mode": "READ_ONLY"
  }
  ```

---

### Fase 1: Solo Lectura (Implementadas)

| Herramienta | Modo Mínimo | Lectura | Idempotente | Destructiva | Descripción |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `project.configure` | `READ_ONLY` | No (Config) | Sí | No | Configura y valida `project_root`, `original_dir`, `output_dir`, `reports_dir` y `backups_dir`. |
| `scene.describe` | `READ_ONLY` | Sí | Sí | No | Devuelve escena actual, unidades, ejes, FPS, estado modificado, nodos principales y plugins. |
| `scene.list_meshes` | `READ_ONLY` | Sí | Sí | No | Lista shapes poligonales con UUID, V/E/F, tipos de cara, shells, fronteras y bounding box (con paginación). |
| `selection.get` | `READ_ONLY` | Sí | Sí | No | Devuelve selección actual, modo objeto/componente y componentes expandidos hasta el límite configurado. |
| `retopo.detect_candidates` | `READ_ONLY` | Sí | Sí | No | Clasifica candidatos a `high_poly` y `retopology` usando densidad, quads, fronteras y relación espacial. |
| `retopo.analyze_mesh` | `READ_ONLY` | Sí | Sí | No | Diagnóstico topológico completo (V/E/F, quads, triángulos, n-gons, non-manifold, lámina, zero-area/length, Euler). |
| `retopo.analyze_symmetry` | `READ_ONLY` | Sí | Sí | No | Evalúa planos bilaterales `X`, `Y`, `Z` con offset real, porcentaje de emparejamiento y nivel de confianza. |
| `retopo.boundary_loops` | `READ_ONLY` | Sí | Sí | No | Agrupa bordes abiertos en loops cerrados, cadenas o ramificaciones y sugiere región anatómica. |
| `viewport.capture` | `READ_ONLY` | Sí | Sí | No | Captura imagen del viewport aislando opcionalmente nodos y restaurando siempre el estado previo del viewport. |

---

### Fase 2: Selección y Roles (Planificadas)

| Herramienta | Modo Mínimo | Lectura | Idempotente | Destructiva | Descripción |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `selection.set` | `PREVIEW` | No | Sí | No | Selecciona objetos o componentes existentes sin modificar geometría. |
| `retopo.confirm_roles` | `PREVIEW` | No | Sí | No | Confirma `high_poly` y `retopology`, guarda reporte JSON versionado y activa la huella de protección high-poly. |

---

### Fase 3: Preview Seguro (Planificadas)

| Herramienta | Modo Mínimo | Lectura | Idempotente | Destructiva | Descripción |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `safety.checkpoint` | `PREVIEW` | No | No | No | Crea una copia recuperable en `backups_dir` sin sobrescribir archivos existentes. |
| `retopo.preview_region` | `PREVIEW` | No | Sí (Undo) | No | Ejecuta operación regional dentro de un undo chunk, valida, captura vistas y deshace (`scene_restored: true`). |

---

### Fase 4: Aplicación y Guardado (Planificadas)

| Herramienta | Modo Mínimo | Lectura | Idempotente | Destructiva | Descripción |
| :--- | :--- | :---: | :---: | :---: | :--- |
| `retopo.apply_region` | `APPLY` | No | No | Sí (Controlada) | Exige preview previo exitoso, crea checkpoint, aplica operación, valida, guarda nueva versión y revalida al reabrir. |
| `retopo.validate` | `READ_ONLY` | Sí | Sí | No | Ejecuta auditoría final sin modificar la escena y devuelve `passed` junto con cada comprobación individual. |
| `scene.save_version` | `APPLY` | No | No | No | Guarda copia con incremento de versión en `output_dir`, rechazando `original_dir` o sobrescrituras. |

