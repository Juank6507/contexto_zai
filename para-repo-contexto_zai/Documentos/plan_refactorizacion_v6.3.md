# contexto_zai/Documentos/plan_refactorizacion_v6.3.md
# Plan v6.3 — Calidad de contexto: pendientes obligatorias, índice preservado, A1 robusto, sort cronológico, resumen riguroso

**Versión:** 6.3
**Fecha:** 2026-09-27
**Autor:** Agente CZAI (Sesión 25, con consenso del Director)
**Estado:** 🚧 Pendiente de implementación.
**Continúa de:** plan v6.2 (fallback al agente con subagentes).
**Spec asociada:** spec_recuperacion_contexto_v6.3.md.

---

## Estructura del plan

El plan se organiza en 5 fases (F1-F5), cada una atendiendo a una de las 5
decisiones del Director. Los cambios son quirúrgicos sobre código existente
(Python + TypeScript).

1. F1 — Garantizar que no queden tareas pendientes antes de terminar.
2. F2 — Preservar índice de chats anteriores (no sobrescribir).
3. F3 — Sección A1 robusta (filtra volcados, garantiza tema completo).
4. F4 — Sort cronológico en ExchangeBuilder y BlockPacker.
5. F5 — Prompt de resumen riguroso (formato rígido).

**Total de archivos nuevos:** 0.
**Total de archivos intervenidos:** 6 (`pipeline.py`, `generation/indice_generator.py`,
  `process/recovery_cycle.py`, `generation/estado_generator.py`,
  `processing/exchange_builder.py`, `processing/block_packer.py`,
  `mini-services/worker-cascade/index.ts`, `config.py`,
  `tests/test_v42_e2e.py`).
**Tests nuevos:** 5 E2E.

---

## F1 — Garantizar que no queden tareas pendientes antes de terminar

**Prioridad:** ALTA — problema #1 del Director.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`pipeline.py`** — añadir `_ejecutar_pending_tasks_obligatorias(result)`:

   ```python
   def _ejecutar_pending_tasks_obligatorias(
       result: OrchestratorResult,
       workspace_dir: Path | str,
   ) -> OrchestratorResult:
       """v6.3: Ejecuta las pending_tasks antes de devolver el resultado.

       Si hay pending_tasks:
       1. Intenta collect_responses() (ejecuta vía proxy APA si disponible).
       2. Si quedan, las marca como error y loggea.
       3. Si todas se resuelven, pending_tasks queda vacío.
       """
       if not result.pending_tasks:
           return result

       # Intentar collect_responses()
       try:
           from contexto_zai.pipeline import collect_responses
           applied = collect_responses(workspace_dir=str(workspace_dir))
           logger.info("v6.3: collect_responses() aplicó %d respuestas", applied)
       except Exception as e:
           logger.warning("v6.3: collect_responses() falló: %s", e)

       # Re-leer pending_tasks tras collect_responses
       from contexto_zai.coordinador.orquestador import Orquestador
       orch = Orquestador(workspace_dir=workspace_dir)
       remaining = orch.leer_tareas_pendientes()

       if remaining:
           logger.warning(
               "v6.3: %d tarea(s) pendientes sin resolver tras collect_responses()",
               len(remaining),
           )
           result.pending_tasks = remaining
           # No marcar success=False: las pending_tasks de fallback son esperadas
           # (el agente las ejecutará con Task tool)
       else:
           result.pending_tasks = []
           logger.info("v6.3: todas las pending_tasks resueltas")

       return result
   ```

2. **`pipeline.py`** — integrar en `run()` después de `_enriquecer_bloques_post_run()`:

   ```python
   result = _enriquecer_bloques_post_run(
       result=result,
       workspace_dir=workspace_dir,
       chat_label=chat_label,
   )
   # v6.3: ejecutar pending_tasks obligatorias
   result = _ejecutar_pending_tasks_obligatorias(
       result=result,
       workspace_dir=workspace_dir,
   )
   return result
   ```

3. **`OrchestratorResult`** (en `process/orchestrator.py`) — añadir campo
   `pending_tasks_resolved: int = 0` para trackear cuántas se resolvieron.

### Tests individuales

- Test: `_ejecutar_pending_tasks_obligatorias()` con pending vacío → no hace nada.
- Test: con pending y collect_responses OK → pending queda vacío.
- Test: con pending y collect_responses falla → pending se mantiene.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F2 — Preservar índice de chats anteriores (no sobrescribir)

**Prioridad:** ALTA — problema #2 del Director.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.7 sesión.

### Qué se hace

1. **`generation/indice_generator.py`** — añadir `_incluir_bloques_anteriores()`:

   ```python
   def _incluir_bloques_anteriores(
       self,
       blocks: list[ThematicBlock],
       workspace_dir: Path | str | None,
   ) -> list[ThematicBlock]:
       """v6.3: Incluye bloques físicos preexistentes del workspace.

       Escanea workspace_dir en busca de bloque_*.md que no estén en
       la lista `blocks` actual. Los añade con flag chat_origen="anterior".
       """
       if not workspace_dir:
           return blocks
       ws = Path(workspace_dir)
       if not ws.exists():
           return blocks

       existing_filenames = {b.filename for b in blocks}
       for p in sorted(ws.glob("bloque_*.md")):
           if p.name not in existing_filenames:
               # Leer temas del bloque preexistente (del header)
               from contexto_zai.models import ThematicBlock
               block = ThematicBlock(filename=p.name)
               # Intentar leer temas del header del archivo
               try:
                   content = p.read_text(encoding="utf-8")
                   # Buscar "# Bloque tematico: tema1, tema2"
                   for line in content.split("\n"):
                       if line.startswith("# Bloque tematico:"):
                           temas_str = line.split(":", 1)[1].strip()
                           block.temas = [t.strip() for t in temas_str.split(",")]
                           break
               except Exception:
                   block.temas = ["anterior"]
               blocks.append(block)
       return blocks
   ```

2. **`generation/indice_generator.py`** — modificar `generate()` para llamar
   a `_incluir_bloques_anteriores()`:

   ```python
   def generate(
       self,
       blocks: list[ThematicBlock],
       chat_label: str = "",
       metadata: Optional[RecoveryMetadata] = None,
       decisiones_summary: str = "",
       attachments_indexados: list = None,
       workspace_dir: Path | str | None = None,  # NUEVO v6.3
   ) -> str:
       # v6.3: incluir bloques de chats anteriores
       if workspace_dir:
           blocks = self._incluir_bloques_anteriores(blocks, workspace_dir)
       # ... resto del método
   ```

3. **`generation/recovery_generator.py`** — pasar `workspace_dir` al
   `IndiceGenerator`:

   ```python
   indice_content = self._indice_gen.generate(
       blocks=blocks,
       chat_label=chat_label,
       metadata=metadata,
       decisiones_summary=decisiones_summary,
       attachments_indexados=attachments_indexados or [],
       workspace_dir=self._workspace_dir,  # NUEVO v6.3
   )
   ```

4. **`process/recovery_cycle.py`** — `_escribir_archivos()` con merge del índice:

   ```python
   def _escribir_archivos(self, recovery_files, workspace_dir):
       for rf in recovery_files:
           target = Path(workspace_dir) / rf.filename
           # v6.3: si es el índice y ya existe, hacer merge
           if rf.filename == "01_indice_recuperacion.md" and target.exists():
               existing = target.read_text(encoding="utf-8")
               rf.content = self._merge_indice(existing, rf.content)
           target.write_text(rf.content, encoding="utf-8")
   ```

### Tests individuales

- Test: `_incluir_bloques_anteriores()` con workspace vacío → no añade nada.
- Test: con workspace con bloque_67.md preexistente → lo añade a la lista.
- Test: merge del índice preserva sección "Bloques de chats anteriores".
- Test: índice final lista los 80 bloques (66 nuevos + 14 anteriores).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/indice_generator.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/recovery_generator.py
```

---

## F3 — Sección A1 robusta (filtra volcados, garantiza tema completo)

**Prioridad:** ALTA — problema #3 del Director.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.6 sesión.

### Qué se hace

1. **`generation/estado_generator.py`** — mejorar `_build_a1()`:

   ```python
   def _build_a1(
       self,
       recent: list[Exchange],
       tema_actual: str = "",
       ultimo_exchange_real: Exchange | None = None,  # NUEVO v6.3
   ) -> str:
       """v6.3: Filtra volcados externos y garantiza tema completo.

       Mejoras:
       1. Si el último intercambio real tiene > A1_VOLCADO_UMBRAL_CHARS chars,
          buscar hacia atrás el último con contenido < umbral.
       2. Tomar TODOS los intercambios del tema activo (no solo el último).
       3. Si la suma supera 16K chars, truncado inteligente (existente).
       """
       if not recent:
           return "Sin actividad reciente registrada."

       # v6.3: filtrar volcados externos
       from contexto_zai.config import A1_VOLCADO_UMBRAL_CHARS
       intercambios_filtrados = []
       for ex in reversed(recent):
           content_len = len(ex.director_msg.content)
           if content_len > A1_VOLCADO_UMBRAL_CHARS:
               logger.info("v6.3 A1: saltando exchange %d (volcado %d chars)",
                          ex.id, content_len)
               continue
           intercambios_filtrados.insert(0, ex)
           break  # Tomar solo el último que cumpla
       if not intercambios_filtrados:
           intercambios_filtrados = recent[-1:]  # fallback al último

       # v6.3: tomar TODOS los intercambios del tema activo
       if tema_actual:
           intercambios_tema = [
               ex for ex in recent
               if ex.topic == tema_actual
               and len(ex.director_msg.content) <= A1_VOLCADO_UMBRAL_CHARS
           ]
       else:
           intercambios_tema = intercambios_filtrados
       if not intercambios_tema:
           intercambios_tema = intercambios_filtrados

       # ... resto del método existente (truncado inteligente)
   ```

2. **`config.py`** — añadir constante:

   ```python
   # v6.3: Umbral para detectar volcados externos en A1
   A1_VOLCADO_UMBRAL_CHARS = 10000  # contenido > 10K se considera volcado
   ```

### Tests individuales

- Test: `_build_a1()` con último exchange de 20K chars → salta al anterior.
- Test: con último exchange de 5K chars → lo usa.
- Test: con tema activo que tiene 3 intercambios → los incluye todos.
- Test: con tema activo que tiene 50 intercambios (>16K) → trunca inteligente.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/generation/estado_generator.py
```

---

## F4 — Sort cronológico en ExchangeBuilder y BlockPacker

**Prioridad:** ALTA — problema #4 del Director.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.3 sesión.

### Qué se hace

1. **`processing/exchange_builder.py`** — añadir sort al final de `build()`:

   ```python
   def build(self, messages: list[Message]) -> list[Exchange]:
       # ... código existente que construye intercambios ...

       # v6.3: ordenar intercambios por start_timestamp ascendente
       exchanges.sort(key=lambda ex: ex.start_timestamp)

       return exchanges
   ```

2. **`processing/block_packer.py`** — añadir sort al inicio de `pack()`:

   ```python
   def pack(
       self,
       exchanges_by_topic: dict[str, list[Exchange]],
   ) -> list[ThematicBlock]:
       # v6.3: ordenar intercambios por start_timestamp dentro de cada tema
       for tema in exchanges_by_topic:
           exchanges_by_topic[tema].sort(key=lambda ex: ex.start_timestamp)

       # ... resto del método existente ...
   ```

### Tests individuales

- Test: `build()` con mensajes desordenados (ts 5, 1, 3, 2, 4) → intercambios
  salen ordenados (1, 2, 3, 4, 5).
- Test: `pack()` con intercambios desordenados → bloques con períodos
  `fecha_inicial < fecha_final`.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/exchange_builder.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/processing/block_packer.py
```

---

## F5 — Prompt de resumen riguroso (formato rígido)

**Prioridad:** ALTA — problema #5 del Director.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.4 sesión.

### Qué se hace

1. **`mini-services/worker-cascade/index.ts`** — reescribir `PROMPT_RESUMEN`:

   ```typescript
   const PROMPT_RESUMEN = (bloqueContent: string) => `Lee el siguiente bloque de intercambios entre un Director y un agente.

   Genera un resumen del bloque con estas reglas RÍGIDAS:

   FORMATO OBLIGATORIO:
   - Un solo párrafo de texto natural (sin secciones, sin listas, sin numeración).
   - Longitud EXACTA entre 600 y 900 caracteres.
   - Exactamente 4 oraciones, separadas por punto y seguido.
   - Sin negritas, sin ALL CAPS, sin emojis.
   - Sin "Decisiones destacadas:", sin "Tema central:", sin etiquetas.

   ESTRUCTURA DE LAS 4 ORACIONES:
   1. Tema central (qué se discutió en el bloque).
   2. Decisiones principales tomadas (si no hay, decir "sin decisiones formales").
   3. Temas específicos mencionados (2-3 keywords máximo).
   4. Tipo de actividad (debugging/diseño/implementación/discusión).

   EJEMPLO de resumen bien formado:
   "Implementación del milestone H2 del plan v4.0 con intervención quirúrgica del EstadoGenerator para reducir el estado actual de 8 a 5 secciones. Se decidió eliminar D2 y D3 del ensamblado pero conservándolos en código, inyectar SubagentLauncher opcional con fallback regex, y añadir 12 auto-tests nuevos. Los temas principales fueron estado_generator, truncado inteligente y subagentes clasificación. La actividad predominante fue implementación con validación de tests reales."

   PROHIBICIONES:
   - No uses "Decisiones destacadas:" ni "Tema central:" ni etiquetas similares.
   - No hagas listas con guiones ni numeración.
   - No superes los 900 caracteres ni bajes de 600.
   - No incluyas código ni rutas de archivos.

   Bloque:
   ${bloqueContent}

   Resumen:`;
   ```

2. **`mini-services/worker-cascade/index.ts`** — actualizar `SYSTEM_PROMPT_HEAVY`:

   ```typescript
   const SYSTEM_PROMPT_HEAVY = "Eres un subagente del sistema de recuperación de contexto contexto_zai. Generas resúmenes en un formato RÍGIDO de 4 oraciones y 600-900 caracteres. No usas secciones, ni listas, ni negritas, ni ALL CAPS. Respondes con un solo párrafo de texto natural.";
   ```

3. **`config.py`** — añadir constantes:

   ```python
   # v6.3: Longitud del RESUMEN
   RESUMEN_MIN_CHARS = 600
   RESUMEN_MAX_CHARS = 900
   ```

### Tests individuales

- Test: `PROMPT_RESUMEN` incluye "600 y 900 caracteres".
- Test: `PROMPT_RESUMEN` incluye "4 oraciones".
- Test: `PROMPT_RESUMEN` incluye "sin secciones, sin listas".
- Test: Worker Bun self-test valida que el prompt tiene las restricciones.

### Validación

```bash
cd /home/z/my-project/contexto_zai/mini-services/worker-cascade
bun run cli.ts --self-test
```

---

## F6 — Tests E2E (5 escenarios)

**Prioridad:** ALTA — valida que todo encaja.
**Dependencias:** F1, F2, F3, F4, F5.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.6 sesión.

### Qué se hace

Añadir 5 tests E2E en `tests/test_v42_e2e.py`:

1. `test_v63_no_quedan_pendientes`: pending_tasks vacío tras `pipeline.run()`.
2. `test_v63_indice_preserva_anteriores`: índice lista bloques preexistentes.
3. `test_v63_a1_sin_volcados`: A1 salta intercambios con > 10K chars.
4. `test_v63_sort_cronologico`: bloques con períodos ordenados.
5. `test_v63_resumen_riguroso`: RESUMEN entre 600-900 chars, 4 oraciones.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
```

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias | Estado |
|---|---|---|---|
| F1 — No quedan pendientes | Sesión 25 (0.5) | ninguna | 🚧 Pendiente |
| F2 — Índice preserva anteriores | Sesión 25 (0.7) | ninguna | 🚧 Pendiente |
| F3 — A1 robusto | Sesión 25 (0.6) | ninguna | 🚧 Pendiente |
| F4 — Sort cronológico | Sesión 25 (0.3) | ninguna | 🚧 Pendiente |
| F5 — Prompt riguroso | Sesión 25 (0.4) | ninguna | 🚧 Pendiente |
| F6 — Tests E2E (5 escenarios) | Sesión 25 (0.6) | F1-F5 | 🚧 Pendiente |

**Total estimado:** 3.1 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| `collect_responses()` falla en F1 | Media | Medio | Catch + log warning + mantener pending_tasks |
| Bloques preexistentes no tienen header legible | Baja | Bajo | Fallback a tema "anterior" |
| `_build_a1()` salta todos los intercambios (todos volcados) | Baja | Medio | Fallback al último disponible |
| Sort por timestamp rompe tests existentes | Baja | Bajo | Tests atómicos verifican |
| Prompt riguroso genera RESUMEN fuera de rango | Media | Bajo | Validación post-generación |

---

**Fin del plan v6.3.**
