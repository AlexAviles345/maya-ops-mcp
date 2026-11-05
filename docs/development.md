# Guía de Desarrollo, Pruebas y Rollback (`development`)

## 1. Flujo de Desarrollo por Fases

El proyecto se construye de manera incremental siguiendo la sección 12 de [`docs/specification.md`](specification.md):

1. **Fase 0:** Base segura y `maya.health` (completada en su rama correspondiente).
2. **Fase 1:** Herramientas de solo lectura (`READ_ONLY`).
3. **Fase 2:** Selección y confirmación de roles (`high_poly` / `retopology`).
4. **Fase 3:** Preview seguro con undo automático y checkpoints.
5. **Fase 4:** Aplicación controlada, validación y guardado versionado.
6. **Fase 5:** Endurecimiento, límites, paginación y pruebas en escenas corruptas.

---

## 2. Ejecución de Pruebas

### Pruebas Unitarias y de Integración con Maya Simulado (`FakeMayaServer`)

No requieren tener Maya abierto; levantan un servidor loopback efímero en `127.0.0.1` que simula el puente de Maya e inyecta casos de fallo (ruido, respuestas truncadas, timeouts, desconexiones):

```powershell
$env:PYTHONPATH = "src;."
py -m unittest discover -s tests -p "test_*.py" -v
```

### Autocomprobación del Servidor MCP (`--self-check`)

```powershell
$env:PYTHONPATH = "src;."
py -m maya_retopo_mcp.server --self-check
```

---

## 3. Reglas de Calidad y Seguridad para Contribuciones

- **Prohibido importar `maya.cmds` o `maya.api` dentro de `src/maya_retopo_mcp/`**: El servidor externo debe ejecutarse en el Python del host sin depender del entorno interno de Maya.
- **Todo handler nuevo en `maya_bridge/` debe registrarse explícitamente** en `maya_bridge/dispatcher.py` y tener un contrato tipado en `src/maya_retopo_mcp/models/`.
- **Prohibido devolver stack traces crudos al cliente**: Toda excepción no controlada se captura, se registra localmente y se transforma en un `McpToolError` con código estructurado.

---

## 4. Instrucciones de Rollback

1. **En Autodesk Maya (si una sesión de puente debe cerrarse):**
   ```python
   from maya_bridge import bootstrap
   bootstrap.stop_server()
   ```
2. **En Git (para revertir una fase o cambio):**
   ```powershell
   # Ver historial de ramas y commits por fase
   git log --oneline --graph --all

   # Volver al commit estable anterior
   git checkout main
   ```
3. **En Escenas de Proyecto:**
   - La carpeta `original/` nunca es tocada por el servidor.
   - Si cualquier versión en `output/` es rechazada, restaurar el último archivo en `backups/` correspondiente al timestamp registrado en el reporte de `reports/`.
