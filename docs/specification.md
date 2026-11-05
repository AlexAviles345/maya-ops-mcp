# Maya Retopo MCP

Especificacion inicial para construir un servidor MCP local que permita a un
agente de IA inspeccionar y asistir trabajos de retopologia en Autodesk Maya de
forma segura, visual, reversible y verificable.

Este documento esta pensado para entregarse a otra IA o a un desarrollador.
Debe tratarse como la fuente inicial de requisitos del proyecto.

## 1. Vision

El proyecto se llamara provisionalmente **Maya Retopo MCP** y su paquete podra
usar el nombre `maya-retopo-mcp`.

La primera version no pretende controlar todo Maya. Su objetivo es resolver el
flujo que se necesito en el proyecto MICEL:

1. Conectarse a una sesion abierta de Maya.
2. Inspeccionar la escena sin modificarla.
3. Identificar candidatos a escultura high-poly y retopologia manual.
4. Permitir que el artista confirme esos roles mediante su seleccion.
5. Analizar quads, n-gons, triangulos, shells, fronteras, non-manifold y
   degeneraciones.
6. Detectar el plano anatomico probable de simetria sin asumir `X = 0`.
7. Capturar el viewport para que el agente pueda comprobar visualmente la
   escena.
8. Crear checkpoints antes de cualquier modificacion.
9. Ejecutar operaciones regionales en modo `preview`, validar y deshacer.
10. Aplicar una region solamente despues de una orden explicita.
11. Guardar resultados en copias versionadas, nunca sobre el original.
12. Generar reportes JSON reproducibles.

Despues del MVP, el servidor podra crecer hacia modelado, materiales,
rigging, skinning, animacion, render, exportacion y administracion de assets.

## 2. Principios no negociables

- El servidor es local y de un solo usuario.
- Toda comunicacion con Maya debe permanecer en loopback/localhost.
- La inspeccion es el modo predeterminado.
- Las herramientas de lectura y escritura deben estar claramente separadas.
- No se expone ejecucion arbitraria de Python o MEL en el MVP.
- Ninguna herramienta puede ejecutar comandos de shell desde Maya.
- No se sobrescriben escenas de `original/`.
- Una malla marcada como high-poly es referencia protegida.
- No se infieren roles solamente por nombres de nodos.
- No se asume que el plano de simetria es `X = 0`.
- Antes de escribir geometria se requiere checkpoint, preview y validacion.
- La malla final debe contener exclusivamente quads, salvo que una politica
  futura autorice expresamente otra cosa.
- No se permiten remesh, booleanas, auto-retopologia, auto-triangulacion o
  reemplazo total de la topologia en el MVP.
- Cada operacion debe devolver evidencia estructurada, no solo texto libre.
- Toda mutacion debe ejecutarse dentro de un undo chunk.
- Un error debe provocar rollback o undo automatico.
- El layout topologico no garantiza deformaciones perfectas: siempre se
  requieren pruebas de rigging y skinning.

## 3. Alcance del MVP

### Incluido

- Autodesk Maya 2027 en Windows.
- Una sesion Maya GUI por servidor.
- Escenas `.ma` y `.mb` ya abiertas en Maya.
- Consultas con `maya.cmds` y `maya.api.OpenMaya`.
- Seleccion de objetos y componentes.
- Analisis topologico determinista.
- Capturas del viewport.
- Checkpoints y guardado versionado.
- Ejecucion de operaciones regionales registradas y permitidas.
- Preview con undo automatico.
- Validacion antes y despues de cada operacion.
- Logs y reportes dentro del proyecto activo.

### No incluido

- Ejecucion libre de codigo enviado por el modelo.
- Servidor accesible desde otras computadoras.
- Generacion 3D mediante servicios externos.
- Descarga automatica de assets.
- Cambios destructivos sin confirmacion.
- Auto-remesh o retopologia generica de un personaje completo.
- Garantia automatica de calidad artistica o deformacion.
- Soporte inicial para Blender, Houdini, 3ds Max o Unreal.

## 4. Arquitectura propuesta

```text
Codex / cliente MCP
        |
        | MCP por stdio
        v
maya-retopo-mcp (Python externo)
        |
        | TCP loopback + mensajes JSON
        v
Maya commandPort / puente Maya
        |
        v
maya.cmds + maya.api.OpenMaya
```

## 5. Modelo de seguridad

### Modos

El servidor debe tener tres modos configurables:

- `READ_ONLY`: solo inspeccion y viewport.
- `PREVIEW`: permite operaciones registradas, pero siempre hace undo.
- `APPLY`: permite guardar cambios despues de checkpoint y validacion.

El modo inicial siempre debe ser `READ_ONLY`.

### Restricciones de rutas

Al conectar un proyecto se declaran:

```json
{
  "project_root": "C:/ruta/proyecto",
  "original_dir": "C:/ruta/proyecto/original",
  "output_dir": "C:/ruta/proyecto/output",
  "reports_dir": "C:/ruta/proyecto/reports",
  "backups_dir": "C:/ruta/proyecto/backups"
}
```

## 6. Herramientas MCP del MVP

- `maya.health`
- `project.configure`
- `scene.describe`
- `scene.list_meshes`
- `selection.get`
- `selection.set`
- `retopo.detect_candidates`
- `retopo.confirm_roles`
- `retopo.analyze_mesh`
- `retopo.analyze_symmetry`
- `retopo.boundary_loops`
- `viewport.capture`
- `safety.checkpoint`
- `retopo.preview_region`
- `retopo.apply_region`
- `retopo.validate`
- `scene.save_version`
