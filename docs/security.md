# Modelo de Seguridad y Esquema de Amenazas

Este documento establece las garantías de seguridad no negociables de **Maya Retopo MCP** y presenta el **Esquema de Amenazas (Threat Model)** exigido antes de habilitar cualquier operación de escritura.

---

## 1. Modos de Operación

El servidor opera bajo una máquina de estados de permisos con tres modos:

| Modo | Estado Inicial | Operaciones Permitidas | Garantía |
| :--- | :--- | :--- | :--- |
| `READ_ONLY` | **Sí (por defecto)** | Inspección de escena, topología, simetría, captura de viewport con restauración. | Ninguna herramienta altera geometría ni deja `modified=True`. |
| `PREVIEW` | No | Todas las de `READ_ONLY` + `selection.set`, `retopo.confirm_roles`, `safety.checkpoint`, `retopo.preview_region`. | Toda mutación ocurre dentro de un *undo chunk* y se deshace antes de responder (`scene_restored: true`). |
| `APPLY` | No | Todas las anteriores + `retopo.apply_region`, `scene.save_version`. | Requiere preview previo válido, checkpoint obligatorio, validación post-operación y guardado en versión nueva dentro de `output/`. |

---

## 2. Esquema de Amenazas (Threat Model)

| ID | Amenaza | Vector de Ataque / Fallo | Mitigación Implementada |
| :--- | :--- | :--- | :--- |
| **T-01** | Ejecución remota o arbitraria de código en Maya | Un prompt malicioso o alucinación del agente intenta enviar Python/MEL arbitrario al `commandPort` de Maya. | El puente `maya_bridge/dispatcher.py` **no evalúa código**. Solo acepta payloads JSON `{ "action": "<id>", "params": {...} }` y valida `<id>` contra un diccionario cerrado (`ALLOWED_HANDLERS`). |
| **T-02** | Exposición del puerto de Maya en la red local | El socket se enlaza a `0.0.0.0` permitiendo que otros equipos en la LAN envíen comandos a Maya. | `command_port.py` y `bootstrap.py` validan explícitamente que el host sea `127.0.0.1` o `localhost`. Cualquier otra IP lanza `SecurityPolicyError` (`NON_LOOPBACK_FORBIDDEN`). |
| **T-03** | Destrucción o sobrescritura de la escena original | Una herramienta guarda cambios sobre el archivo en `original/` o sobrescribe una versión previa en `output/`. | `policies/paths.py` impone: (1) `original_dir` es estrictamente de solo lectura; (2) `output_dir` exige nombres versionados nuevos y falla si el archivo destino ya existe (`FILE_ALREADY_EXISTS`). |
| **T-04** | Path Traversal o escritura fuera del proyecto | Uso de `..`, barras mezcladas, rutas UNC (`\\host\share`), unidades externas o enlaces simbólicos para escapar de `project_root`. | Se rechazan cadenas con `..` o prefijos UNC antes de resolver, se aplica `Path.resolve()` y se verifica `resolved.is_relative_to(project_root)`. |
| **T-05** | Alteración silenciosa de la escultura High-Poly | Un handler regional modifica accidentalmente los vértices o el transform de la malla de referencia `high_poly`. | `policies/protected_mesh.py` calcula y verifica una huella inmutable (`MeshFingerprint`: DAG path, UUID, V/E/F, bounding box y hash SHA-256 de topología/posiciones) antes y después de cada operación. Si difiere, se hace rollback inmediato (`HIGH_POLY_CHANGED`). |
| **T-06** | Corrupción de escena por fallo a mitad de una operación | Una excepción ocurre después de modificar la mitad de los vértices de una región. | Toda mutación se envuelve en un bloque `try/finally` con `cmds.undoInfo(openChunk=True)` / `closeChunk=True` seguido de `cmds.undo()` automático en caso de error o modo `PREVIEW`. |
| **T-07** | Bloqueo (Hang) o denegación de servicio en Maya | Respuestas gigantescas, bucles infinitos o llamadas desde hilos secundarios que corrompen el DAG de Maya. | (1) Timeout de socket configurable en el cliente MCP; (2) límite máximo de bytes por mensaje (`max_payload_bytes`); (3) ejecución despachada al hilo principal de Maya (`executeInMainThreadWithResult`). |
| **T-08** | Filtración de rutas del sistema o datos sensibles en errores | Stack traces completos devueltos al cliente MCP con variables locales o rutas del usuario. | `errors.py` devuelve al cliente únicamente códigos de error tipados, mensajes limpios y sugerencias de recuperación. Los detalles técnicos se registran localmente con sanitización en `logging_config.py`. |

---

## 3. Reglas de Aislamiento de Rutas

Cada proyecto conectado define 5 directorios canónicos dentro de `project_root`:

- `project_root`: Raíz contenedora del proyecto.
- `original_dir`: **Solo lectura absoluta**. Prohibido escribir, renombrar o eliminar.
- `output_dir`: Destino único para escenas versionadas (`*_v001.mb`, `*_v002.mb`). Prohibido sobrescribir.
- `reports_dir`: Destino único para reportes JSON de diagnóstico, confirmación de roles y validación.
- `backups_dir`: Destino único para checkpoints previos a mutaciones. Prohibido sobrescribir.
