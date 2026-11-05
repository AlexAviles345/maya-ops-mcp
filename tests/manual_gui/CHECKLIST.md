# Lista de Comprobación Manual en Autodesk Maya 2027 GUI

Esta lista debe ejecutarse siempre sobre **copias desechables** de escenas antes de dar por aprobada cada fase (Secciones 10, 11 y 15).

## Fase 0: Base Segura y `maya.health`
- [ ] Levantar `maya_bridge.bootstrap.start_server(host="127.0.0.1", port=7001)` en el Script Editor de Maya 2027.
- [ ] Invocar `maya.health` desde el cliente MCP y verificar que devuelve `"ok": true`, `"maya_version": "2027"`, `"mode": "READ_ONLY"`.
- [ ] Confirmar que `maya.health` **no** altera `cmds.file(q=True, modified=True)`.
- [ ] Cerrar Maya o ejecutar `bootstrap.stop_server()` durante una llamada y verificar que el servidor MCP devuelve `"code": "MAYA_CONNECTION_ERROR"` sin colgarse.

## Fases Posteriores (1 a 4)
- [ ] Selección de objetos y componentes (`selection.get`, `selection.set`).
- [ ] Captura real de viewport (`viewport.capture`) y restauración exacta del estado del viewport (isolación, cámara, wireframe on shaded).
- [ ] Operación `retopo.preview_region` visible en el proceso y deshecha automáticamente (`scene_restored: true`).
- [ ] Undo automático después de fallo provocado en un handler regional.
- [ ] Guardado versionado (`scene.save_version`) en `output/` y reapertura con validación.
- [ ] Comprobación con escena con cambios sin guardar (`modified: true`).
