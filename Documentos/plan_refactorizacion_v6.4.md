# contexto_zai/Documentos/plan_refactorizacion_v6.4.md
# Plan v6.4 — Unificación de fuentes, filtro completo, síntesis práctica, sort global

**Versión:** 6.4
**Fecha:** 2026-09-28
**Autor:** Agente CZAI (Sesión 26, con consenso del Director)
**Estado:** 🚧 Pendiente de implementación.
**Continúa de:** plan v6.3.
**Spec asociada:** spec_recuperacion_contexto_v6.4.md.

---

## Estructura del plan

5 fases (F1-F5) que atienden las 5 decisiones del Director.

1. F1 — Eliminar regex, consolidar decisiones del LLM en 02_decisiones_clave.md.
2. F2 — Filtrar tool_calls en A1 (agent_msgs) + aplicar ContentCleaner.
3. F3 — G0.B = resumen del bloque del tema activo.
4. F4 — Mismo prompt riguroso en fallback que en Worker Bun.
5. F5 — Sort global + timestamps válidos + soporte non-chat.

**Total de archivos intervenidos:** 7 (`pipeline.py`, `generation/estado_generator.py`,
  `generation/decisiones_generator.py`, `process/recovery_cycle.py`,
  `processing/block_packer.py`, `models.py`, `config.py`,
  `tests/test_v42_e2e.py`).
**Tests nuevos:** 5 E2E.

---

## F1 — Eliminar regex, consolidar decisiones del LLM

**Prioridad:** ALTA. **Estado:** 🚧 Pendiente. **Estimación:** 0.6 sesión.

### Qué se hace

1. **`process/recovery_cycle.py`**: `_build_decisiones_generator()` elimina el
   `DecisionExtractor` regex. Devuelve `DecisionesGenerator()` sin extractor
   (modo offline placeholder, como en v4.2 con launcher).

2. **`pipeline.py`**: añadir `_consolidar_decisiones_llm(workspace_dir)`:
   - Lee todos los `_responses/bloque_*_decisiones.txt`.
   - Parsea cada línea con formato `DECISION: ... | ALCANCE: ...`.
   - Construye una lista de `Decision` objects.
   - Las escribe en `02_decisiones_clave.md` con formato estructurado.

3. **`pipeline.py`**: integrar `_consolidar_decisiones_llm()` en
   `_ejecutar_pending_tasks_obligatorias()` (después de `collect_responses()`).

4. **`generation/decisiones_generator.py`**: `_format_markdown()` usa formato
   `## D01 -- {title}` con `DECISION: ...` y `ALCANCE: ...` (no texto crudo).

### Tests

- `test_v64_decisiones_consolidadas`: `_consolidar_decisiones_llm()` lee 3 archivos
  `_responses/bloque_*_decisiones.txt` y genera `02_decisiones_clave.md` con 3 decisiones.

---

## F2 — Filtrar tool_calls en A1

**Prioridad:** ALTA. **Estado:** 🚧 Pendiente. **Estimación:** 0.5 sesión.

### Qué se hace

1. **`generation/estado_generator.py`**: `_build_a1()` amplía el filtro de volcados:
   - Verifica `len(ex.director_msg.content) > A1_VOLCADO_UMBRAL_CHARS` (ya existe).
   - **NUEVO**: verifica `len(msg.content) > A1_VOLCADO_UMBRAL_CHARS` para cada
     `msg` en `ex.agent_msgs`. Si cualquier `agent_msg` supera el umbral, se salta
     el intercambio.

2. **`generation/estado_generator.py`**: `_build_a1()` aplica `ContentCleaner`:
   - Antes de añadir el contenido del agente al texto de A1, pasa cada `msg.content`
     por `ContentCleaner.format_message_content(msg.content, msg.role)`.
   - Esto parsea `tool_calls` a texto legible ("Archivo creado: ruta", "Comando: desc", etc.).

3. **`generation/estado_generator.py`**: importar `ContentCleaner` o recibirlo
   como parámetro.

### Tests

- `test_v64_a1_sin_tool_calls`: A1 no contiene `{"type": "tool_calls"` después de
  procesar intercambios con `tool_calls` en `agent_msgs`.

---

## F3 — G0.B = resumen del bloque del tema activo

**Prioridad:** ALTA. **Estado:** 🚧 Pendiente. **Estimación:** 0.5 sesión.

### Qué se hace

1. **`generation/estado_generator.py`**: `_build_g0_b()` reescrito:
   - Recibe `workspace_dir` (ya lo tiene `self._workspace_dir`).
   - Busca en el workspace los `bloque_*.md` que contienen el tema activo
     (leyendo el header `# Bloque tematico: <tema>` o el `_metadata.json`).
   - Lee el `RESUMEN:` al inicio de cada bloque encontrado.
   - Si 1 bloque → G0.B = ese RESUMEN.
   - Si N bloques → G0.B = concatenación de RESUMEN separados por `\n\n---\n\n`.
   - Si no encuentra bloques → G0.B = aviso "No hay bloques con RESUMEN para el tema activo."

2. **Eliminar** la tarea `SINTESIS_CONTEXTO` y el placeholder de G0.B.

### Tests

- `test_v64_g0b_con_resumen`: G0.B contiene el texto del RESUMEN del bloque
  del tema activo.

---

## F4 — Mismo prompt en fallback que en Worker Bun

**Prioridad:** ALTA. **Estado:** 🚧 Pendiente. **Estimación:** 0.3 sesión.

### Qué se hace

1. **`config.py`**: añadir `PROMPT_RESUMEN_RIGIDO` — versión Python del prompt
   del Worker Bun (idéntico al `PROMPT_RESUMEN` de `index.ts`).

2. **`pipeline.py`**: `_construir_pending_task_para_bloque()` reemplaza el prompt
   genérico por `PROMPT_RESUMEN_RIGIDO` + el contenido del bloque.

### Tests

- `test_v64_fallback_mismo_prompt`: el prompt de `_construir_pending_task_para_bloque()`
  contiene "600 y 900 caracteres" y "4 oraciones".

---

## F5 — Sort global + timestamps válidos + non-chat

**Prioridad:** ALTA. **Estado:** 🚧 Pendiente. **Estimación:** 0.5 sesión.

### Qué se hace

1. **`processing/block_packer.py`**: al final de `pack()`, después de construir
   todos los bloques, ordenar los intercambios de cada bloque por `start_timestamp`
   globalmente:
   ```python
   for block in blocks:
       block.exchanges.sort(key=lambda ex: ex.start_timestamp)
   ```

2. **`models.py`**: `Exchange.end_datetime` valida `end_timestamp`:
   ```python
   @property
   def end_datetime(self):
       ts = self.end_timestamp
       if ts and ts > 0:
           return datetime.fromtimestamp(ts, tz=timezone.utc)
       # Fallback: usar start_timestamp (no director_msg.timestamp que puede ser distinto)
       return self.start_datetime
   ```

3. **`models.py`**: `ThematicBlock.period_str` usa `end_datetime` con fallback:
   ```python
   @property
   def period_str(self):
       if not self.exchanges:
           return "sin datos"
       first = self.exchanges[0].start_datetime
       last = self.exchanges[-1].end_datetime
       if last < first:
           last = first  # evitar período invertido
       return f"{first.strftime('%Y-%m-%d')} -> {last.strftime('%Y-%m-%d')}"
   ```

4. **Soporte non-chat**: si todos los `start_timestamp` son 0.0 (docs externos),
   el sort es estable (no cambia el orden) y `period_str` devuelve "sin datos
   cronológicos" (porque first == last == epoch 1970).

### Tests

- `test_v64_sort_global`: bloque con intercambios de 2 temas distintos tiene
  intercambios ordenados globalmente por timestamp.
- `test_v64_timestamp_valido`: `period_str` no invierte fechas cuando
  `end_timestamp = 0`.

---

## Orden de ejecución

| Fase | Sesión | Dependencias | Estado |
|---|---|---|---|
| F1 — Eliminar regex, consolidar LLM | 0.6 | ninguna | 🚧 Pendiente |
| F2 — Filtrar tool_calls en A1 | 0.5 | ninguna | 🚧 Pendiente |
| F3 — G0.B = resumen del bloque | 0.5 | ninguna | 🚧 Pendiente |
| F4 — Mismo prompt en fallback | 0.3 | ninguna | 🚧 Pendiente |
| F5 — Sort global + timestamps | 0.5 | ninguna | 🚧 Pendiente |

**Total estimado:** 2.4 sesiones.

---

**Fin del plan v6.4.**
