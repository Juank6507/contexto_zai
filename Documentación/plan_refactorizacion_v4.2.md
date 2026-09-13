# Plan v4.2 — Implementación del proceso contexto_zai como bibliotecario que sirve al agente

**Versión:** 4.2
**Fecha:** 2026-09-13
**Autor:** Agente CZAI (Sesión 17, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.0 (enmendado v4.1 por H9 mal enfocado, ahora corregido).
**Spec asociada:** spec_recuperacion_contexto_v4.2.md.

---

## Estructura del plan

El plan se organiza en 5 fases (F1–F5). Cada fase es independiente y entregable por separado. El orden respeta las dependencias:

1. Primero desmontar el H9 mal implementado.
2. Luego crear la clase de coordinación (la que sirve al agente).
3. Luego crear la clase de procesamiento (con sus 3 subclases).
4. Luego conectar las clases al proceso.
5. Al final, validar con datos reales.

**Total de archivos nuevos:** 6 (las 2 clases base + 6 subclases, en archivos atómicos).
**Total de archivos intervenidos:** ~8 (generadores, recovery_cycle, orchestrator, pipeline).
**Tests nuevos:** 6 atómicos + 1 E2E.

---

## F1 — Desmontar el H9 mal implementado

**Prioridad:** ALTA — limpieza previa, no se puede construir sobre lo mal hecho.
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### Qué se desmonta

El H9 que implementé mal en la sesión anterior introdujo:
- Modelos `SubagentTask` y `SubagentResponse` en `models.py` (estos se conservan, son útiles).
- `self._deferred_tasks` en `EstadoGenerator`, `DecisionesGenerator`, `Subdivider` (se desmonta).
- Método `apply_responses()` en los generadores (se desmonta).
- Campo `pending_tasks` en `RecoveryCycleResult` y `OrchestratorResult` (se conserva, se usa en F2).
- Función `apply_subagent_responses()` en `pipeline.py` (se desmonta).

### Archivos intervenidos

1. `generation/estado_generator.py` — quitar `self._deferred_tasks`, `deferred_tasks`, `apply_responses`, `_format_d4_response`, `_format_a1_resumen_response`, `_replace_section`, `_append_a1_resumen`. Restaurar `_build_d4` y `_build_a1` a su estado original (regex fallback, sin intentar sub.run() síncrono).
2. `generation/decisiones_generator.py` — quitar `self._deferred_tasks`, `deferred_tasks`, `apply_responses`, `_parse_subagent_response`, `_build_decision`. Restaurar `_extract_with_subagent` a su estado original.
3. `processing/subdivider.py` — quitar `self._deferred_tasks`, `deferred_tasks`, `apply_responses`. Restaurar `_generate_legible_name` a su estado original.
4. `pipeline.py` — quitar `apply_subagent_responses()`. Conservar el resto.

### Lo que se conserva

- `SubagentTask` y `SubagentResponse` en `models.py` — se usan en F2.
- Campo `pending_tasks` en `RecoveryCycleResult` y `OrchestratorResult` — se usa en F2.
- El cableado del `SubagentLauncher` en `Orchestrator.activate()` — se ajusta en F4.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/decisiones_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/subdivider.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

Todos deben pasar (con los tests actualizados para reflejar el desmontaje).

---

## F2 — Clase de coordinación proceso-agente

**Prioridad:** ALTA — es la herramienta del agente, la necesitan F3 y F4.
**Dependencias:** F1 (desmontaje previo).
**Estimación:** 1 sesión.

### Archivos nuevos

1. `contexto_zai/coordinador/__init__.py` — paquete que exporta las 3 subclases.
2. `contexto_zai/coordinador/entregador_tareas.py` (atómico, standalone, con auto-tests).
   - Clase `EntregadorTareas`.
   - Método `publicar(tasks: list[SubagentTask], workspace_dir: Path)` — escribe `_pending_tasks.json`.
   - Método `leer(workspace_dir: Path) -> list[SubagentTask]` — lee `_pending_tasks.json` (lo usa el agente).
   - Método `limpiar(workspace_dir: Path)` — borra `_pending_tasks.json` y `_responses/` tras aplicar.
3. `contexto_zai/coordinador/recogedor_respuestas.py` (atómico, standalone).
   - Clase `RecogedorRespuestas`.
   - Método `leer(workspace_dir: Path) -> list[SubagentResponse]` — lee `_responses/{task_id}.txt`.
   - Método `procesar(responses: list[SubagentResponse], procesador) -> dict` — entrega el resultado estructurado al proceso.
   - Método `escribir_respuesta(task_id: str, response: str, workspace_dir: Path)` — escribe una respuesta (lo usa el subagente o el agente).
4. `contexto_zai/coordinador/orquestador.py` (atómico, standalone).
   - Clase `Orquestador`.
   - Método `coordinar(procesador, input_data, workspace_dir) -> dict` — coordina el flujo completo:
     1. El procesador prepara las tareas.
     2. El `EntregadorTareas` las publica.
     3. (El agente las lee y lanza subagentes — fuera del proceso.)
     4. El `RecogedorRespuestas` lee las respuestas cuando están listas.
     5. El procesador integra las respuestas.
     6. Devuelve el resultado estructurado.
   - Método `hay_tareas_pendientes(workspace_dir: Path) -> bool`.
   - Método `hay_respuestas_listas(workspace_dir: Path) -> bool`.

### Archivos intervenidos

5. `contexto_zai/pipeline.py` — agregar función `collect_responses(workspace_dir)` que invoca al `Orquestador` para procesar las respuestas y devolver el resultado estructurado al agente.

### Detalle

- El "lugar accesible" son archivos en el workspace, no un mini-servicio HTTP.
- `_pending_tasks.json` contiene la lista de `SubagentTask` (task_id, purpose, prompt, context).
- `_responses/{task_id}.txt` contiene la respuesta cruda de cada subagente.
- El agente lee `_pending_tasks.json`, lanza los subagentes, y estos escriben en `_responses/`.
- El agente llama a `pipeline.collect_responses()` y el `Orquestador` se encarga del resto.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/entregador_tareas.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/recogedor_respuestas.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/coordinador/orquestador.py
```

---

## F3 — Clase de procesamiento con 3 subclases

**Prioridad:** ALTA — es donde se unifican los 4 mecanismos y las mejoras semánticas.
**Dependencias:** F2 (usa el `Orquestador`).
**Estimación:** 1.5 sesiones.

### Archivos nuevos

1. `contexto_zai/procesadores/__init__.py` — paquete que exporta las 3 subclases.
2. `contexto_zai/procesadores/procesador_documento.py` (atómico, standalone).
   - Clase `ProcesadorDocumento`.
   - Método `procesar(source_type, source_path, jwt, workspace_dir) -> dict`:
     - Decide según tamaño (trivial, mediano, grande).
     - Para trivial: devuelve `needs_agent_read: true`.
     - Para mediano: prepara una tarea, le pide al `Orquestador` que la coordine.
     - Para grande: usa el flujo de 3 niveles (reutiliza `Divisor` y `Conciliador` existentes), coordinado por el `Orquestador`.
   - Reutiliza `DocumentoIndexerSubagent` (su lógica de lectura y clasificación).
   - Reutiliza `DocumentDelegator` (la decisión de delegar).
   - Reutiliza `Divisor` y `Conciliador` para el caso grande.
3. `contexto_zai/procesadores/procesador_intercambios.py` (atómico, standalone).
   - Clase `ProcesadorIntercambios`.
   - Método `procesar(modo, intercambios, workspace_dir, context) -> dict`:
     - `modo` es uno de: `RESTRICCIONES_TEMA`, `RESUMEN_TRUNCADO`, `DECISIONES`, `NOMBRE_LEGIBLE`, `CLASIFICACION_TEMAS`.
     - Prepara la tarea con `IntercambiosClasificadorSubagent.build_prompt()`.
     - Le pide al `Orquestador` que la coordine.
     - Procesa la respuesta y la entrega estructurada.
   - Reutiliza `ClasificadorSubagent` (H1) como clase base.
   - Reutiliza los modos del `IntercambiosClasificadorSubagent`.
4. `contexto_zai/procesadores/procesador_consulta.py` (atómico, standalone).
   - Clase `ProcesadorConsulta`.
   - Método `procesar(pregunta, workspace_dir, max_results) -> dict`:
     - Identifica bloques candidatos (keyword search en nombres de temas, índice, contenido).
     - Decide según tamaño total (cabe en un subagente o hay que dividir).
     - Prepara la(s) tarea(s), le pide al `Orquestador` que la(s) coordine.
     - Consolida las respuestas y devuelve la respuesta final.
   - Reutiliza la lógica de `query_context` (M8) que ya funciona.

### Archivos intervenidos (preparación para F4)

5. `contexto_zai/subagents/documento_indexer_subagent.py` — extraer la lógica de lectura y clasificación para que la pueda reutilizar `ProcesadorDocumento`. No se elimina la clase, se refactoriza para que su lógica sea reutilizable.
6. `contexto_zai/subagents/intercambios_clasificador_subagent.py` — verificar que `build_prompt()` es accesible para `ProcesadorIntercambios`. Ya lo es, no debería necesitar cambios.

### Detalle

- Las 3 subclases comparten el patrón: reciben input, deciden según tamaño, preparan tarea(s), le piden al `Orquestador` que coordine, procesan la respuesta, entregan resultado estructurado.
- Para el caso grande, `ProcesadorDocumento` y `ProcesadorConsulta` usan el flujo de 3 niveles (Divisor + Conciliador), coordinado por el `Orquestador` (no por TaskBridgeServer).
- La regla de eficiencia: un subagente para tareas medianas, varios solo para tareas grandes que no caben en uno.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_documento.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_intercambios.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/procesadores/procesador_consulta.py
```

---

## F4 — Conectar las clases al proceso

**Prioridad:** ALTA — integra todo.
**Dependencias:** F2, F3.
**Estimación:** 1 sesión.

### Archivos intervenidos

1. `contexto_zai/generation/estado_generator.py` — en `_build_d4` y `_build_a1`, en vez de intentar `sub.run()` síncrono o acumular `deferred_tasks`, llamar a `ProcesadorIntercambios.procesar(modo=RESTRICCIONES_TEMA, ...)` que prepara la tarea y la publica vía `EntregadorTareas`. El resultado se aplica en F2 cuando el agente llama a `collect_responses()`.
2. `contexto_zai/generation/decisiones_generator.py` — en `_extract_with_subagent`, llamar a `ProcesadorIntercambios.procesar(modo=DECISIONES, ...)` por lote. Las tareas se publican y se aplican después.
3. `contexto_zai/processing/subdivider.py` — en `_generate_legible_name`, llamar a `ProcesadorIntercambios.procesar(modo=NOMBRE_LEGIBLE, ...)` para preparar la tarea. El nombre temporal se usa hasta que el agente lance el subagente y el proceso aplique la respuesta.
4. `contexto_zai/processing/classifier.py` — (opcional, si se implementa clasificación de temas con subagente) añadir modo `CLASIFICACION_TEMAS` que use `ProcesadorIntercambios` para asignar temas reales en vez de regex.
5. `contexto_zai/process/recovery_cycle.py` — tras `generate_all()`, recolectar las tareas publicadas por los generadores y devolverlas en `RecoveryCycleResult.pending_tasks`. No llama `apply_responses()` — eso lo hace el `Orquestador` cuando el agente llama a `collect_responses()`.
6. `contexto_zai/process/orchestrator.py` — ya cablea el `SubagentLauncher` (de H9). Ajustar para que use el `EntregadorTareas` para publicar las tareas pendientes.
7. `contexto_zai/pipeline.py`:
   - `run()` — devolver `pending_tasks` en el resultado (ya lo hace).
   - `ampliar_contexto()` — usar `ProcesadorDocumento` en vez de la lógica inline actual.
   - `query_context()` — usar `ProcesadorConsulta` en vez de la lógica inline actual.
   - `collect_responses()` — ya agregada en F2, ahora se conecta al `Orquestador` y a los procesadores.
8. `contexto_zai/process/recovery_cycle.py` — en `_index_attachments()`, usar `ProcesadorDocumento` en vez del `DocumentoIndexerSubagent` directo.

### Detalle

- Los generadores ya no llaman `sub.run()` síncrono ni acumulan `deferred_tasks`. Llaman a `ProcesadorIntercambios.procesar()` que prepara la tarea y la publica.
- El `Orquestador` se encarga de coordinar: publicar tareas, esperar respuestas, integrarlas.
- El `pipeline.collect_responses()` es la única función que el agente llama tras lanzar los subagentes — no hay trabajo manual.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/decisiones_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/subdivider.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/process/recovery_cycle.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/process/orchestrator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F5 — Desmontar lo reemplazado y validar con datos reales

**Prioridad:** MEDIA — limpieza final y prueba real.
**Dependencias:** F4.
**Estimación:** 0.5 sesión.

### Qué se desmonta

1. `contexto_zai/subagents/_task_bridge.py` — queda como código legacy, no se usa en el flujo principal. Se añade un comentario al inicio indicando que está deprecado.
2. `contexto_zai/subagents/task_bridge_server.py` — lo mismo, legacy.
3. `mini-services/task-bridge/` — el mini-servicio HTTP en puerto 8087 ya no se necesita para el flujo principal. Se conserva por si se necesita para otros casos, pero no se inicia automáticamente.

### Validación con datos reales

1. Restaurar el JWT del Director (vía bookmarklet si hace falta).
2. Ejecutar `pipeline.run()` contra el chat real `13b43432-...`.
3. Verificar que:
   - Los tres archivos se generan (con regex fallback).
   - `pending_tasks` se llena con las tareas de D4, A1, decisiones, nombres.
4. El agente lanza los subagentes con el Task tool usando los prompts de `_pending_tasks.json`.
5. Los subagentes escriben sus respuestas en `_responses/`.
6. El agente llama a `pipeline.collect_responses()`.
7. Verificar que:
   - `00_estado_actual.md` tiene D4 con las restricciones reales.
   - `00_estado_actual.md` tiene A1 con el resumen del contenido truncado.
   - `02_decisiones_clave.md` tiene las decisiones reales con alcance.
   - `_metadata.json` tiene los nombres legibles.
8. Probar `query_context()` con una pregunta real y verificar que la respuesta llega consolidada.
9. Probar `ampliar_contexto()` con un archivo pequeño y uno grande (CZAI-01.pdf).

### Test E2E

**Archivo:** `contexto_zai/tests/test_v42_e2e.py`

**Cobertura:**
1. `EntregadorTareas` publica y lee tareas en `_pending_tasks.json`.
2. `RecogedorRespuestas` lee respuestas de `_responses/` y las entrega estructuradas.
3. `Orquestador` coordina el flujo completo.
4. `ProcesadorDocumento` procesa archivo pequeño (directo), mediano (un subagente), grande (3 niveles).
5. `ProcesadorIntercambios` procesa cada modo.
6. `ProcesadorConsulta` procesa una consulta con modo directo y distribuido.
7. `pipeline.run()` devuelve `pending_tasks`.
8. `pipeline.collect_responses()` aplica las respuestas y actualiza los archivos.
9. Flujo completo: `pipeline.run()` → agente lanza subagentes → `collect_responses()` → archivos actualizados.
10. Comunicación de errores: si un subagente falla, el error sube al Director.

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias |
|---|---|---|
| F1 — Desmontar H9 mal implementado | Sesión 18 | ninguna |
| F2 — Clase de coordinación | Sesión 18 | F1 |
| F3 — Clase de procesamiento | Sesión 18 (o 19) | F2 |
| F4 — Conexión al proceso | Sesión 19 | F2, F3 |
| F5 — Desmontar lo reemplazado + validar | Sesión 19 | F4 |

**Total estimado:** 2 sesiones.

## Verificación final

```bash
# Tests atómicos
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 run_all_tests.py

# Test E2E v4.2
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 test_v42_e2e.py

# Prueba real con datos del chat 13b43432
# (requiere JWT del Director)
```

Todos deben pasar.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El `Orquestador` con archivos no maneja bien la concurrencia | Baja | Medio | Los archivos se escriben atómicamente (write temp + rename). |
| El agente no llama a `collect_responses()` tras lanzar subagentes | Media | Alto | `pipeline.run()` devuelve un mensaje claro indicando que hay tareas pendientes. |
| El flujo de 3 niveles refactorizado rompe la prueba real | Media | Alto | Los tests E2E validan con datos reales antes de cerrar F5. |
| Los generadores quedan en estado inconsistente | Baja | Medio | Los generadores siempre escriben con regex primero, y `collect_responses()` actualiza después. |
| El `ProcesadorConsulta` no encuentra bloques candidatos | Baja | Bajo | Devuelve "no hay información relevante" (como ya hace `query_context`). |

---

**Fin del plan v4.2.**
