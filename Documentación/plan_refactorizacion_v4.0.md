# contexto_zai/Documentación/plan_refactorizacion_v4.0.md
# Plan v4.0 — Implementación del proceso contexto_zai como bibliotecario siempre disponible

**Versión:** 4.1 (enmienda H9)
**Fecha:** 2026-09-13
**Autor:** Agente CZAI (Sesión 17)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.0.
**Spec asociada:** spec_recuperacion_contexto_v4.0.md (también enmendada a v4.1).
**Enmienda H9:** introduce el patrón diferido para M3/M4/M7/M9-grande,
cablea el `SubagentLauncher` en el `Orchestrator`, y cierra M6-bg (muerte
silenciosa) porque su causa raíz se elimina.

---

## Estructura del plan

El plan se organiza en 8 milestones (H1-H8). Cada milestone es independiente y entregable por separado. El orden respeta las dependencias:

1. Primero la clase base común de subagentes (M7) — la necesitan M3, M4, M8.
2. Después M3 (estado con 5 secciones + truncado inteligente).
3. Después M4 (decisiones con subagente y alcance).
4. Después M8 (consulta bajo demanda).
5. Después M6 (diagnóstico del pipeline en background) — independiente.
6. Después M9 (ampliación de contexto) — independiente.
7. Después M10 (pulir export/import) — independiente.
8. Al final M5 (testing del bookmarklet y persistencia del JWT) — independiente.

**Total de archivos nuevos:** 3 (clase base + 1 subclase nueva + tests E2E)
**Total de archivos intervenidos:** ~10
**Tests nuevos:** 7 atómicos + 1 E2E + tests de diagnóstico para M6

---

## H1 — Clase base común `ClasificadorSubagent` (M7)

**Prioridad:** ALTA — la necesitan M3, M4 y M8.
**Dependencias:** ninguna.
**Estimación:** 1 sesión.

### Archivos nuevos

1. `contexto_zai/subagents/clasificador_subagent.py` (atómico, standalone, con auto-tests en `__main__`).
   - Clase base abstracta `ClasificadorSubagent` con la lógica común: `build_prompt(context)` (abstracto), `run(context)`, `parse_response(raw)` (abstracto).
   - Recibe un `SubagentLauncher` por inyección de dependencias.
2. `contexto_zai/subagents/intercambios_clasificador_subagent.py` (atómico, standalone).
   - Subclase `IntercambiosClasificadorSubagent` que hereda de `ClasificadorSubagent`.
   - Implementa `build_prompt` y `parse_response` para el caso de recibir intercambios del chat.
   - Se usa en M3 (D4, A1), M4 (decisiones), M7 (nombres legibles de subtemas), M8 (consultas por bloque).

### Archivos modificados

3. `contexto_zai/subagents/documento_indexer_subagent.py` — refactorizado para heredar de `ClasificadorSubagent`. Su input sigue siendo archivos/links. Comportamiento idéntico hacia afuera, reutiliza lógica común.
4. `contexto_zai/config.py` — agregar constantes `CLASIFICADOR_MAX_CONTEXT_TOKENS=15000`, `CLASIFICADOR_TIMEOUT_SECONDS=60`.
5. `contexto_zai/subagents/__init__.py` — exportar las nuevas clases.

### Detalle

- La clase base no se instancia directamente. Es abstracta.
- Las subclases se diferencian por el input, no por la lógica de invocación.
- No se mantienen clases paralelas con fallback regex.
- Si el subagente falla, `run()` devuelve un objeto con `success=False` y el detalle del error (timeout, TaskBridgeServer no responde, respuesta vacía, error de parseo). El llamador propaga el error, no se lo traga.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/subagents/clasificador_subagent.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/subagents/intercambios_clasificador_subagent.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/subagents/documento_indexer_subagent.py
```

---

## H2 — `EstadoGenerator` con 5 secciones y truncado inteligente (M3)

**Prioridad:** ALTA — es la función central del proceso. Tras una compresión de contexto, el agente lee `00_estado_actual.md` como uno de los tres puntos de entrada obligatorios. M3 garantiza que ese archivo sea operativo.
**Dependencias:** H1 (usa `IntercambiosClasificadorSubagent` para D4 y A1).
**Estimación:** 1 sesión.

### Archivos intervenidos

1. `contexto_zai/generation/estado_generator.py` — cambios quirúrgicos:
   - Eliminar `_build_d2` y `_build_d3` y sus llamadas desde `generate()`.
   - Intervenir `_build_d4` para que enfoque el tema activo (no los últimos 10 intercambios genéricos) y use `IntercambiosClasificadorSubagent` para interpretar las restricciones.
   - Intervenir `_build_a1` para que tome el tema activo en orden cronológico con truncado inteligente: ~16K de contexto textual + ~4K de resumen del contenido truncado hecho por `IntercambiosClasificadorSubagent`.
   - Intervenir `_build_a2` y `_build_a3` para ampliar los patrones regex (más tipos de rutas y de errores).
   - Intervenir `_build_a4` para que analice los últimos intercambios y detecte qué quedó pendiente, en vez de repetir "continuar con la instrucción".
   - Intervenir `_assemble` para que ensamble las 5 secciones nuevas (D1, D4, A1, A2, A3, A4) en vez de 8.
   - Actualizar los auto-tests en `__main__` para que esperen 5 secciones, no 8.
2. `contexto_zai/config.py` — constantes `ESTADO_TRUNCADO_TEXTUAL_TOKENS=16000`, `ESTADO_TRUNCADO_RESUMEN_TOKENS=4000` (aproximadas, no rígidas).
3. `contexto_zai/generation/recovery_generator.py` — verificar que sigue funcionando con el `EstadoGenerator` intervenido (no cambia la signature, no debería romper nada).

### Detalle

- El `EstadoGenerator` no se reescribe: se hacen cambios quirúrgicos en cada método.
- La clase recibe el `SubagentLauncher` por inyección de dependencias (igual que el `RecoveryGenerator` ya lo hace). Si no se pasa, los métodos que requieren subagente fallan con error claro.
- Si el subagente falla en D4 o A1, el error sube al Director — no se cae a fallback regex.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
# Verificar que genera 5 secciones (D1, D4, A1, A2, A3, A4), no 8.
```

---

## H3 — `DecisionesGenerator` con subagente y alcance (M4)

**Prioridad:** ALTA. Tras una compresión de contexto, el agente lee `02_decisiones_clave.md` como uno de los tres puntos de entrada obligatorios. M4 garantiza que las decisiones sean reales y capturen el alcance.
**Dependencias:** H1 (usa `IntercambiosClasificadorSubagent`).
**Estimación:** 1 sesión.

### Archivos intervenidos

1. `contexto_zai/generation/decisiones_generator.py` — cambios quirúrgicos:
   - Reemplazar el mecanismo de detección regex por el `IntercambiosClasificadorSubagent`.
   - El `generate()` recibe los intercambios en lotes (cantidad configurable) y pasa cada lote al subagente.
   - El subagente distingue entre aprobaciones genéricas (se descartan) y decisiones reales (se documentan).
   - Para cada decisión real, captura el alcance: a qué tarea se refiere, qué incluye, qué no incluye.
   - El `generate()` deduplica (una decisión puede detectarse en varios lotes) y trunca al límite de tokens del archivo.
   - La signature `generate(exchanges, from_timestamp) -> (content, summary)` se mantiene.
   - Actualizar los auto-tests en `__main__` para que verifiquen que las decisiones son reales y tienen alcance.
2. `contexto_zai/config.py` — constantes `DECISIONES_LOTE_SIZE=30`, `DECISIONES_MAX_CONTEXT_TOKENS=12000`.
3. `contexto_zai/generation/recovery_generator.py` — verificar que sigue funcionando con el `DecisionesGenerator` intervenido.

### Detalle

- El `DecisionesGenerator` no se reescribe.
- El prompt del subagente incluye ejemplos positivos y negativos para calibrar la distinción entre aprobación genérica y decisión real.
- Si el subagente falla, el error sube al Director.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/decisiones_generator.py
# Verificar que no aparecen "Correcto" ni aprobaciones genéricas como decisiones.
```

---

## H4 — `query_context` para consulta bajo demanda (M8 revisado)

**Prioridad:** ALTA — es el mecanismo central del bibliotecario.
**Dependencias:** ninguna (no depende de H1 porque no usa `IntercambiosClasificadorSubagent` ni `SubagentLauncher`).
**Estimación:** 1 sesión.

**Hallazgo de pruebas reales (Sesión 16):** Los subagentes no tienen Task tool. Un subagente SÍ tiene `Read` y `Bash`. Un solo subagente que lee varios bloques produce respuestas más completas y requiere una sola invocación del Task tool. El TaskBridgeServer y el polling manual NO son necesarios para consultas.

### Diseño

`query_context` funciona así:
1. La función Python identifica bloques candidatos (keyword search en nombres de temas, índice y contenido de bloques).
2. Calcula el tamaño total de los bloques candidatos.
3. Si el tamaño total < `QUERY_DIRECT_MODE_THRESHOLD_TOKENS` (100K): **modo directo**.
4. Si el tamaño total >= umbral: **modo distribuido**.
5. En modo directo: lanza 1 subagente que lee los bloques con `Read` y responde.
6. En modo distribuido: lanza N subagentes (uno por lote de bloques) en paralelo, consolida.
7. La función devuelve la respuesta.

**Importante:** el agente principal lanza los subagentes directamente con el Task tool. No usa TaskBridgeServer, no usa `_task_bridge.py`, no hace polling. La función `query_context` prepara los prompts y devuelve la información para que el agente principal lance los subagentes.

### Archivos intervenidos

1. `contexto_zai/pipeline.py` — reescribir `query_context`:
   - Lee `_metadata.json` para identificar bloques candidatos.
   - Busca keywords en nombres de temas, contenido del índice y contenido de los bloques.
   - Calcula tamaño total de bloques candidatos.
   - Elige modo (directo o distribuido) según el umbral.
   - Prepara el prompt del subagente con la pregunta y las rutas de los bloques.
   - En modo directo: devuelve el prompt para 1 subagente.
   - En modo distribuido: devuelve N prompts para N subagentes en paralelo.
   - El agente principal ejecuta el/los Task tool y consolida.
2. `contexto_zai/config.py` — agregar `QUERY_DIRECT_MODE_THRESHOLD_TOKENS=100000`.

### Detalle

- No se crea mini-servicio HTTP.
- No se usa TaskBridgeServer para consultas.
- No se usa `SubagentLauncher` ni `_task_bridge.py` para consultas.
- El subagente usa `Read` para leer los bloques directamente del filesystem.
- Si el subagente falla, el error sube al Director (no silencioso).

### Validación

```bash
# Auto-tests en pipeline.py (mock launcher para tests unitarios)
cd /home/z/my-project/contexto_zai && python pipeline.py

# Test real con datos del contexto recuperado
# El agente principal lanza 1 subagente que lee los bloques y responde
```

---

## H5 — Diagnóstico del pipeline en background (M6)

**Prioridad:** MEDIA (no bloqueante pero importante para estabilidad).
**Dependencias:** ninguna.
**Estimación:** 1 sesión (puede requerir más si el diagnóstico es complejo).

### Archivos nuevos

1. `contexto_zai/tests/test_pipeline_background.py` — tests que reproducen las condiciones reales del fallo:
   - Pipeline corriendo en background con `nohup setsid ... </dev/null` (igual que en la Sesión 11).
   - Subagentes lanzados en paralelo con `ThreadPoolExecutor`.
   - Polling HTTP al `TaskBridgeServer` esperando respuestas.
   - El Bash tool cerrando su process tree al terminar.
   - Medición de uso de memoria (descartar OOM), CPU, duración (descartar timeout del Bash tool), presencia de SIGTERM/SIGKILL.
   - Captura de logs en nivel DEBUG de `subagents._task_bridge`, `processing.divisor`, `process.recovery_cycle`, `subagents.divisor_subagent`.

### Detalle

- **No se interviene código del pipeline en este milestone.** Solo se diagnostica.
- El diagnóstico produce un informe que describe qué mata el proceso.
- En función del diagnóstico, se define la intervención en un milestone siguiente (puede ser un H5b).

### Validación

```bash
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 test_pipeline_background.py
# Documenta el hallazgo: OOM / timeout / SIGKILL / etc.
```

---

## H6 — `Subdivider` con nombres legibles (M7)

**Prioridad:** MEDIA.
**Dependencias:** H1 (usa `IntercambiosClasificadorSubagent`).
**Estimación:** 0.5 sesión.

### Archivos intervenidos

1. `contexto_zai/processing/subdivider.py` — cambios quirúrgicos:
   - Intervenir `_subdivide_temporal` para que, en vez de generar nombres compuestos ilegibles (`general_general_2026sep09_2026sep09_2_...`), llame a `IntercambiosClasificadorSubagent` con las keywords del tema y los primeros intercambios representativos.
   - El subagente devuelve un nombre legible en `snake_case` (por ejemplo, `autenticacion_jwt`).
   - El nombre legible se guarda en `_metadata.json` como parte del mapeo `tema_a_archivo`.
   - El `IndiceGenerator` ya lee `tema_a_archivo` de la metadata, así que muestra el nombre legible automáticamente.
   - No se modifica el modelo `ThematicBlock`.
2. `contexto_zai/config.py` — constantes `SUBDIVIDER_NAMER_MAX_CONTEXT_TOKENS=2000`, `SUBDIVIDER_NAMER_MAX_PALABRAS=5`.

### Detalle

- No se crea clase `TemaNamer` separada — la llamada al subagente va dentro del `Subdivider`.
- Si el subagente falla, el error sube al Director.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/subdivider.py
# Verificar que los subtemas tienen nombres legibles, no compuestos.
```

---

## H7 — `ampliar_contexto` para fuentes externas (M9)

**Prioridad:** MEDIA.
**Dependencias:** ninguna (reusa `DocumentoIndexerSubagent` existente, que ya hereda de `ClasificadorSubagent` tras H1).
**Estimación:** 1 sesión.

### Archivos intervenidos

1. `contexto_zai/pipeline.py` — agregar función pública `ampliar_contexto(source_type, source_path, jwt=None, metadata=None)`:
   - Recibe `source_type` (`"url"` o `"file"`), `source_path`, `jwt` (si es URL de Z.ai), `metadata` opcional.
   - Para archivos chicos: devuelve `{needs_agent_read: true, path: source_path}` para que el agente lo lea directo.
   - Para archivos grandes: lo descarga, lo clasifica con `DocumentoIndexerSubagent` (o `index_document_large` si > 50K tokens), agrega el resultado como nuevos bloques al directorio `contexto_recuperacion/`, actualiza `01_indice_recuperacion.md` y `_metadata.json`.
   - Para URLs: descarga con `requests` directamente dentro de la función (no módulo nuevo), lo clasifica igual que un archivo grande.
   - Agrega el campo `source` en `_metadata.json` (mapeo `archivo → source`) para distinguir bloques externos de los del chat.
2. `contexto_zai/config.py` — constantes `AMPLIAR_SMALL_FILE_THRESHOLD_TOKENS=5000`, `AMPLIAR_URL_DOWNLOAD_TIMEOUT=30`, `AMPLIAR_URL_MAX_SIZE_BYTES=50_000_000`.

### Detalle

- No se crea módulo `UrlDownloader` nuevo — la descarga va inline con `requests`.
- No se crea módulo `ampliar_contexto.py` separado — la función va en `pipeline.py`.
- No se modifica el modelo `ThematicBlock` — el campo `source` va en `_metadata.json`.
- Si la URL es de un chat de Z.ai (`/s/{share_id}` o `/c/{chat_id}`), usa el flujo normal de extracción de chat, no el de ampliación.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
from contexto_zai.pipeline import ampliar_contexto
# Test con archivo pequeño (devuelve needs_agent_read=true)
# Test con archivo grande (lo indexa y agrega al contexto)
"
```

---

## H9 — Patrón diferido + cablear launcher (NUEVO, enmienda v4.1)

**Prioridad:** ALTA — despierta la lógica de M3/M4/M7/M9-grande que quedó dormida.
**Dependencias:** H1 (ClasificadorSubagent), H2 (EstadoGenerator), H3 (DecisionesGenerator), H6 (Subdivider).
**Estimación:** 1.5 sesiones.

### Contexto

El diagnóstico de la Sesión 17 reveló que H2, H3 y H6 se implementaron
en código pero su lógica de subagentes nunca se activaba por dos razones:

1. El `Orchestrator` no pasa `SubagentLauncher` al `RecoveryCycle`, así que
   los generadores se quedan en modo regex (backward compatible).
2. Aunque se cableara el launcher, los generadores llaman `sub.run()`
   síncronamente, lo que causa deadlock: el agente está bloqueado corriendo
   el script Python y no puede lanzar subagentes con el Task tool al mismo
tiempo.

H9 resuelve ambas: cablea el launcher Y convierte las llamadas síncronas
a llamadas diferidas (el proceso prepara prompts, el agente los ejecuta
con el Task tool, el proceso aplica las respuestas).

### Regla de oro (H9)

**El agente principal es el único que lanza subagentes.** El proceso Python
prepara el trabajo (prompts) y aplica las respuestas, pero nunca ejecuta
subagentes él mismo. Esto elimina el TaskBridgeServer, el polling HTTP,
y el deadlock síncrono de raíz.

### Archivos nuevos

1. `contexto_zai/models.py` — añade dos modelos:
   - `SubagentTask`: prompt diferido con `task_id`, `purpose`, `prompt`, `context`.
   - `SubagentResponse`: respuesta del subagente con `task_id`, `success`, `response`, `error`.
   - Auto-tests en `__main__` para ambos.

### Archivos intervenidos

2. `contexto_zai/generation/estado_generator.py` — cambios quirúrgicos:
   - Añade `self._deferred_tasks: list[SubagentTask] = []` en `__init__`.
   - Añade propiedad `deferred_tasks`.
   - En `_build_d4`: si hay launcher, construir prompt con `sub.build_prompt()`,
     acumular como `SubagentTask(task_id="estado_d4", purpose="estado.d4", ...)`.
     NO llamar `sub.run()`. Caer al regex para el output inmediato.
   - En `_build_a1`: igual para el resumen del contenido truncado, acumular como
     `SubagentTask(task_id="estado_a1_resumen", purpose="estado.a1_resumen", ...)`.
   - Añade método `apply_responses(responses: list[SubagentResponse]) -> None`
     que reescribe D4 y A1 en el archivo `00_estado_actual.md` del workspace
     con las respuestas reales de los subagentes.

3. `contexto_zai/generation/decisiones_generator.py` — cambios quirúrgicos:
   - Añade `self._deferred_tasks: list[SubagentTask] = []` en `__init__`.
   - Añade propiedad `deferred_tasks`.
   - En `_extract_with_subagent`: para cada lote, construir prompt con
     `sub.build_prompt()`, acumular como `SubagentTask(task_id=f"decisiones_lote_{i}", ...)`.
     NO llamar `sub.run()`. Devuelve lista vacía para el output inmediato.
   - Añade método `apply_responses(responses: list[SubagentResponse]) -> str`
     que reescribe el contenido de `02_decisiones_clave.md` con las decisiones
     reales parseadas de las respuestas.

4. `contexto_zai/processing/subdivider.py` — cambios quirúrgicos:
   - En `_subdivide_temporal`: cuando hay launcher y se necesita nombre legible,
     construir prompt con `sub.build_prompt()`, acumular como `SubagentTask(task_id=f"subdivider_nombre_{i}", ...)`.
     NO llamar `sub.run()`. Usar el nombre basado en fecha (backward compatible).
   - Añade propiedad `deferred_tasks` para exponer las tareas acumuladas.
   - Añade método `apply_responses(responses: list[SubagentResponse]) -> dict`
     que devuelve un mapeo `{nombre_temporal → nombre_legible}` para que el
     proceso renombre los bloques y actualice `_metadata.json`.

5. `contexto_zai/process/recovery_cycle.py` — cambios quirúrgicos:
   - En `run()`: tras llamar a `recovery_gen.generate_all()`, recolectar las
     `SubagentTask` de `EstadoGenerator`, `DecisionesGenerator` y `Subdivider`.
   - Las acumula en `RecoveryCycleResult.pending_tasks` (nuevo campo).
   - Añade método `apply_subagent_responses(responses: list[SubagentResponse])`
     que delega a los generadores y reescribe los archivos.

6. `contexto_zai/process/orchestrator.py` — cambio quirúrgico:
   - En `activate()`: crear `SubagentLauncher()` y pasarlo al `RecoveryCycle`
     vía `subagent_launcher=launcher`.
   - Devolver las `pending_tasks` en `OrchestratorResult` (nuevo campo).

7. `contexto_zai/pipeline.py` — cambios quirúrgicos:
   - `run()`: devolver las `pending_tasks` en el resultado.
   - Nueva función `apply_subagent_responses(responses: list[SubagentResponse],
     workspace_dir=...)` que invoca el `Orchestrator.apply_subagent_responses`
     o directamente los generadores para reescribir los archivos.
   - `ampliar_contexto()`: para archivos grandes, usar patrón diferido en vez
     de llamar `sub.run()` síncrono.

### Detalle

- **No se elimina** `SubagentLauncher`, `_task_bridge.py`, ni `TaskBridgeServer`.
  Se conservan por si se necesitan para otros casos (por ejemplo, lanzamiento
  en background real con polling del agente). Pero no se usan en el flujo
  principal de H9.
- Los generadores mantienen el fallback regex para el output inmediato: el
  archivo se escribe con regex primero, y se actualiza con las respuestas de
  los subagentes cuando el agente llama a `apply_subagent_responses()`.
- Si el agente no llama a `apply_subagent_responses()` (por ejemplo, no hay
  subagentes pendientes), el archivo queda con regex (backward compatible).
- **No se crea clase paralela** ni se duplica lógica. El patrón diferido
  reutiliza `ClasificadorSubagent.build_prompt()` que ya existe.

### Flujo del agente principal (patrón diferido)

```
1. Agente llama a pipeline.run(chat_id, jwt, ...)
2. pipeline.run() devuelve result con result.pending_tasks: list[SubagentTask]
3. Si pending_tasks está vacío: terminado (no hay subagentes pendientes).
4. Si no: agente lanza los subagentes con el Task tool usando los prompts.
   - Puede lanzarlos en paralelo (múltiples Task tools en un solo mensaje).
   - Cada subagente devuelve su respuesta.
5. Agente llama a pipeline.apply_subagent_responses(responses: list[SubagentResponse])
6. El proceso reescribe los archivos con las respuestas reales.
7. Done.
```

### Validación

```bash
# Auto-tests en models.py
PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py

# Auto-tests en estado_generator.py (con y sin launcher)
PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py

# Auto-tests en decisiones_generator.py (con y sin launcher)
PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/decisiones_generator.py

# Auto-tests en subdivider.py (con y sin launcher)
PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/subdivider.py

# Test real: pipeline.run() con launcher, verificar pending_tasks
# Test real: apply_subagent_responses() con respuestas mock
# Test real: archivos 00_estado_actual.md y 02_decisiones_clave.md actualizados
```

---

## Test E2E v4.1

**Archivo:** `contexto_zai/tests/test_v41_e2e.py`

**Cobertura:**
1. `SubagentTask` y `SubagentResponse` modelos funcionan (H9).
2. `EstadoGenerator` con launcher acumula `SubagentTask` diferidas (H9).
3. `DecisionesGenerator` con launcher acumula `SubagentTask` diferidas (H9).
4. `Subdivider` con launcher acumula `SubagentTask` diferidas (H9).
5. `RecoveryCycle` devuelve `pending_tasks` en el resultado (H9).
6. `Orchestrator` cablea el launcher y pasa `pending_tasks` al resultado (H9).
7. `pipeline.run()` devuelve `pending_tasks` (H9).
8. `pipeline.apply_subagent_responses()` reescribe los archivos con las
   respuestas reales (H9).
9. Flujo completo: `pipeline.run()` → agente lanza subagentes →
   `pipeline.apply_subagent_responses()` → archivos actualizados con
   D4 interpretado, A1 con truncado inteligente, decisiones reales,
   nombres legibles.
10. Comunicación de errores: si un subagente falla, el error sube al
    Director (no silencioso).

**Prioridad:** BAJA.
**Dependencias:** ninguna.
**Estimación:** 0.5 sesión.

### Archivos intervenidos (M10)

1. `contexto_zai/context/exporter.py` — cambios quirúrgicos en `_build_instrucciones`:
   - Reordenar los pasos: primero leer los tres puntos de entrada (`00_estado_actual.md`, `01_indice_recuperacion.md`, `02_decisiones_clave.md`), después recién lanzar subagentes para detalle.
   - El orden actual tiene `02_decisiones_clave.md` después de "lanzar subagente para detalle", lo cual está mal.
2. `contexto_zai/context/importer.py` — verificar que `import_from()` devuelve el contenido de `_instrucciones_recuperacion.md` con el orden nuevo (lo que ya hace, solo que con el orden nuevo).

### Archivos nuevos (M5 — testing)

3. `contexto_zai/tests/test_bookmarklet_persistencia.py` — tests que:
   - Verifican que el bookmarklet funciona en un sandbox nuevo (no solo en el actual).
   - Verifican que el JWT persiste en `~/.czai/credentials.json` entre sesiones del mismo sandbox.
   - Simulan la conexión del Director con el bookmarklet y verifican que el endpoint `/api/czai/recibir-jwt` escribe correctamente.

### Detalle

- M5 no interviene código del bookmarklet (ya funciona). Solo agrega tests.
- M10 es un cambio quirúrgico en `_build_instrucciones`: reordenar 5 pasos. No se agregan archivos nuevos al `.zip` — ya incluye `_instrucciones_recuperacion.md` y `_paquete.json`.

### Validación

```bash
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 test_bookmarklet_persistencia.py
# Verifica persistencia del JWT y funcionamiento del bookmarklet.

# Para M10:
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
from contexto_zai.pipeline import export_context, import_context
path = export_context(chat_id='test-789')
instrucciones = import_context(zip_path=path)
# Verificar que las instrucciones tienen los 3 puntos de entrada primero, después subagentes.
"
```

---

## Test E2E v4.0

**Archivo:** `contexto_zai/tests/test_v40_e2e.py`

**Cobertura:**
1. `ClasificadorSubagent` base y `IntercambiosClasificadorSubagent` subclase funcionan (H1).
2. `EstadoGenerator` genera 5 secciones (no 8) y A1 tiene truncado inteligente (H2).
3. `DecisionesGenerator` detecta decisiones reales con alcance, no falsos positivos (H3).
4. `query_context` responde consultas de forma completa y abarcadora (H4).
5. `Subdivider` genera nombres legibles (H6).
6. `ampliar_contexto` con archivo pequeño devuelve `needs_agent_read=true`, con archivo grande lo indexa (H7).
7. `export_context` + `import_context` con instrucciones en orden correcto (H8).
8. Simulación de compresión de contexto: el agente lee los tres puntos de entrada y puede retomar la tarea pendiente sin información adicional.
9. Comunicación de errores: si un subagente falla, el error sube al Director (no silencioso).
10. Bookmarklet persiste el JWT entre sesiones (H8/M5).

**Actualizar:** `tests/run_all_tests.py` para incluir los nuevos módulos atómicos + el E2E v4.0.

---

## Orden de ejecución recomendado

| Milestone | Sesión estimada | Dependencias | Estado |
|---|---|---|---|
| H1 — Clase base `ClasificadorSubagent` | Sesión 12 | ninguna | ✅ Hecho |
| H2 — `EstadoGenerator` 5 secciones + truncado inteligente | Sesión 12 (o 13) | H1 | ✅ Hecho (regex fallback) |
| H3 — `DecisionesGenerator` con subagente y alcance | Sesión 13 | H1 | ✅ Hecho (regex fallback) |
| H4 — `query_context` consulta bajo demanda | Sesión 13 (o 14) | H1 | ✅ Hecho (patrón diferido) |
| H5 — ~~Diagnóstico del pipeline en background~~ | Sesión 14 | ninguna | ✅ Cerrado por H9 |
| H6 — `Subdivider` con nombres legibles | Sesión 14 | H1 | ✅ Hecho (regex fallback) |
| H7 — `ampliar_contexto` fuentes externas | Sesión 15 | ninguna | ✅ Hecho (small OK, grande pendiente H9) |
| H8 — Pulir export/import + testing bookmarklet | Sesión 15 | ninguna | Pendiente |
| **H9 — Patrón diferido + cablear launcher** (NUEVO) | Sesión 17 | H1, H2, H3, H6 | Pendiente |
| Test E2E v4.1 | Sesión 17 | todos | Pendiente |

**Total estimado:** 2 sesiones adicionales (H8 + H9 + E2E).

**Notas sobre el estado de H2/H3/H6:** los hitos H2, H3 y H6 se
implementaron en código, pero su lógica de subagentes (D4, A1 resumen,
decisiones reales, nombres legibles) quedó dormida porque el `Orchestrator`
no cableaba el `SubagentLauncher` y porque el patrón síncrono `sub.run()`
causaba deadlock. H9 despierta esa lógica: cablea el launcher Y convierte
las llamadas `sub.run()` síncronas a llamadas diferidas (construcción de
prompt + acumulación como `SubagentTask` + respuesta aplicada por el
agente principal vía `pipeline.apply_subagent_responses()`).

## Verificación final

Después de completar todos los milestones:

```bash
# Tests atómicos (47 actuales + nuevos = ~55)
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 run_all_tests.py

# Test E2E v3.6 (debe seguir pasando, actualizando los que prueban comportamiento que cambia)
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 test_v36_e2e.py

# Test E2E v4.0
cd /home/z/my-project/contexto_zai/tests && PYTHONPATH=/home/z/my-project python3 test_v40_e2e.py

# Lint
cd /home/z/my-project && bun run lint
```

Todos deben pasar.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Subagentes LLM consumen mucho tiempo (>60s) | Media | Alto | Timeout configurado en `config.py`. Error sube al Director. |
| `ClasificadorSubagent` base sale mal diseñada y rompe `DocumentoIndexerSubagent` | Baja | Alto | Auto-tests en `documento_indexer_subagent.py` validan que sigue funcionando igual. |
| Eliminar D2 y D3 del `EstadoGenerator` rompe tests existentes | Alta | Medio | Actualizar los auto-tests que esperaban 8 secciones para que esperen 5. |
| Diagnóstico de M6 (H5) no encuentra la causa | Media | Medio | Si los tests no reproducen el fallo, se documenta lo observado y se hace una segunda ronda con más instrumentación. |
| `ampliar_contexto` con URLs grandes (>50MB) | Baja | Bajo | Constante `AMPLIAR_URL_MAX_SIZE_BYTES` limita la descarga. |
| El bookmarklet no persiste el JWT en sandbox nuevo | Media | Medio | H8/M5 incluye tests específicos de persistencia. |

---

**Fin del documento 3.**
