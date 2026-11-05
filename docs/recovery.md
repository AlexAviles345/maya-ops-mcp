# Guía de Recuperación ante Incidentes (`recovery`)

Este documento describe los procedimientos paso a paso para recuperar escenas, estado de Maya y configuración del servidor ante errores o interrupciones durante flujos de trabajo con **Maya Retopo MCP**.

---

## 1. Principio de Inmutabilidad de `original/`

- La carpeta `original/` **jamás es abierta en modo escritura ni modificada** por ninguna herramienta de `maya-retopo-mcp`.
- En el peor escenario posible (cierre abrupto de Maya o corrupción de disco en `output/`), el archivo fuente en `original/` permanece intacto.

---

## 2. Recuperación desde Checkpoints (`backups/`)

Antes de cada ejecución de `retopo.apply_region` (o manualmente mediante `safety.checkpoint`), el servidor genera una copia recuperable en `backups/`:

1. Localiza el último reporte en `reports/` (por ejemplo `apply_hands_v1_v001.json`) o lista la carpeta `backups/` ordenada por fecha.
2. Verifica las huellas `high_poly_fingerprint` y `retopology_fingerprint` registradas en el reporte.
3. Abre la copia de respaldo en Maya 2027 y guárdala como una nueva versión limpia en `output/` (por ejemplo `escena_v008.mb`).
4. Vuelve a ejecutar `retopo.confirm_roles` y `retopo.validate` para verificar que todas las comprobaciones (`passed: true`) estén en verde.

---

## 3. Manejo de Versiones Rechazadas (`*.rejected`)

Si `retopo.apply_region` detecta una discrepancia al reabrir y revalidar un archivo recién guardado en `output/`:

1. El servidor renombra automáticamente el archivo defectuoso con el sufijo `.rejected` (ej. `micel_v003.mb.rejected`).
2. El bloque de undo revierte la geometría en memoria y conserva la escena anterior activa.
3. **Acción recomendada:** No utilices archivos `.rejected` para producción; consérvalos únicamente para análisis forense o elimínalos tras restaurar el checkpoint de `backups/`.

---

## 4. Alerta `HIGH_POLY_CHANGED`

Si cualquier herramienta devuelve el código `"HIGH_POLY_CHANGED"`:

1. Significa que el DAG path, UUID, conteo V/E/F, bounding box o hash estructural SHA-256 de la escultura de referencia cambió respecto a la confirmación inicial.
2. El servidor aborta la operación y ejecuta rollback automático.
3. **Acción recomendada:**
   - Ejecuta `retopo.validate` para inspeccionar qué propiedad de la `high_poly` cambió.
   - Si el artista movió o desbloqueó accidentalmente la escultura en Maya, haz `Undo` en Maya o restaura el último checkpoint de `backups/`.

---

## 5. Recuperación del Puente en Maya (`maya_bridge`)

Si Maya deja de responder en el puerto local o devuelve `MAYA_BUSY` / `MAYA_TIMEOUT`:

```python
from maya_bridge import bootstrap

# Reiniciar limpiamente el listener loopback en Maya Script Editor
bootstrap.stop_server()
bootstrap.start_server(host="127.0.0.1", port=7001)
```
