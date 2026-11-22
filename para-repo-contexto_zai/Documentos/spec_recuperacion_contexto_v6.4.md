# contexto_zai/Documentos/spec_recuperacion_contexto_v6.4.md
# Spec v6.4 — Unificación de fuentes, filtro completo, síntesis práctica, sort global

**Versión:** 6.4
**Fecha:** 2026-09-28
**Autor:** Agente CZAI (Sesión 26, con consenso del Director)
**Estado:** Spec pendiente de implementación.
**Especifica continuación de:** spec v6.3 (calidad de contexto).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v6.4.md.

---

## 1. Propósito

La v6.3 corrigió 5 defectos pero la auditoría a fondo del contexto generado
reveló **6 desviaciones** adicionales con causas raíz en el código. El Director
dio 5 decisiones claras para corregirlas, agrupadas en:

1. **Eliminar el regex de decisiones** — sobra, el LLM extrae mejor.
2. **Filtrar tool_calls en A1** — el filtro debe verificar `agent_msgs`, no solo `director_msg`.
3. **G0.B = resumen del bloque A1** — la síntesis no es otra cosa que el resumen del tema activo.
4. **Mismo prompt en fallback** — el subagente de fallback debe usar el mismo prompt riguroso del Worker Bun.
5. **Sort global + timestamps válidos + non-chat** — orden cronológico global + validación de timestamps + soporte para docs sin cronología.

### 1.1. Decisiones del Director (textuales)

> **#1**: "Por qué dos formas si basta con la segunda. Eliminamos el regex y nos quedamos con el LLM. Por supuesto se tiene que lograr copiar las 26 decisiones del LLM al archivo 02_decisiones_clave.md."

> **#2**: "Hacer la modificación necesaria."

> **#3**: "Esa síntesis no tiene que ser otra cosa que el resumen del bloque Sección A1. Para esto hay que analizar si el tema está disperso en más de un bloque o si está en un sólo bloque que entonces bastaría con el resumen del bloque."

> **#4**: "Tienen que ser generados con el mismo prompt en este caso el del Worker Bun."

> **#5**: "Independientemente del bloque el orden cronológico del bloque tiene que mantenerse también en el tema, pero hay que revisar si los timestamps de bloque es correcto y pertenece a los metadatos del chat. También respecto a esto es importante implementar soluciones para cuando el contexto no viene de chat sino de otra documentación donde no existe orden cronológico."

## 2. Los 6 problemas que la v6.4 ataca

| # | Problema | Causa raíz | Fase |
|---|---|---|---|
| 1 | `02_decisiones_clave.md` tiene 4 decisiones (regex) en vez de 26 (LLM) | `DecisionExtractor` regex y `DecisionesGenerator` LLM trabajan en paralelo sin consolidar | F1 |
| 2 | Sección A1 contiene JSON crudo de `tool_calls` del agente | Filtro F3 verifica `director_msg.content`, no `agent_msgs[*].content`; `ContentCleaner` no se aplica a A1 | F2 |
| 3 | G0.B (Síntesis) vacía con placeholder | Tarea `SINTESIS_CONTEXTO` nunca se ejecuta; G0.B debería ser el resumen del bloque del tema activo | F3 |
| 4 | RESUMEN de fallback usa prompt distinto al Worker Bun | `_construir_pending_task_para_bloque()` usa prompt genérico, no el riguroso F5 | F4 |
| 5 | Período invertido en bloque multi-tema | Sort es por tema, no global; `end_timestamp` puede ser 0 | F5 |
| 6 | Formato de decisiones regex incorrecto | Mismo problema que #1 — el regex produce formato crudo, no estructurado | F1 (se elimina con el regex) |

## 3. La solución: 5 mejoras quirúrgicas

### 3.1. F1 — Eliminar regex, consolidar decisiones del LLM

**Principio**: una sola fuente de decisiones: el LLM. El `DecisionExtractor`
regex se elimina. Las decisiones extraídas por el Worker Bun (o subagentes
fallback) desde `_responses/bloque_NN_decisiones.txt` se consolidan en
`02_decisiones_clave.md`.

**Implementación**:

1. **`process/recovery_cycle.py`**: `_build_decisiones_generator()` deja de
   crear `DecisionExtractor` regex. Devuelve `DecisionesGenerator()` sin
   extractor ni launcher (modo offline placeholder).

2. **`pipeline.py`**: `_ejecutar_pending_tasks_obligatorias()` (F1 de v6.3)
   se amplía: después de `collect_responses()`, lee todos los archivos
   `_responses/bloque_*_decisiones.txt`, los parsea (formato
   `DECISION: ... | ALCANCE: ...`), y los consolida en
   `02_decisiones_clave.md` con el formato estructurado.

3. **`generation/decisiones_generator.py`**: `_format_markdown()` usa el
   formato `DECISION: ... | ALCANCE: ...` (no el formato crudo actual).

### 3.2. F2 — Filtrar tool_calls en A1 (agent_msgs)

**Principio**: el filtro de volcados externos (F3 de v6.3) debe verificar
tanto `director_msg.content` como `agent_msgs[*].content`. Además, el
`ContentCleaner` debe aplicarse al contenido de A1 para parsear `tool_calls`
a texto legible.

**Implementación**:

1. **`generation/estado_generator.py`**: `_build_a1()` aplica el filtro de
   volcados a `agent_msgs` también (no solo `director_msg`). Si el contenido
   de cualquier `agent_msg` supera `A1_VOLCADO_UMBRAL_CHARS`, se salta ese
   intercambio.

2. **`generation/estado_generator.py`**: `_build_a1()` aplica
   `ContentCleaner.format_message_content()` al contenido del agente antes
   de incluirlo en el texto. Esto parsea `tool_calls` a texto legible.

### 3.3. F3 — G0.B = resumen del bloque del tema activo

**Principio**: la sección G0.B (Síntesis del contexto) no es una tarea LLM
diferida. Es simplemente el `RESUMEN:` del bloque (o bloques) donde aparece
el tema activo.

**Implementación**:

1. **`generation/estado_generator.py`**: `_build_g0_b()` ya no devuelve un
   placeholder. En su lugar, busca en el workspace los bloques que contienen
   el tema activo, lee el `RESUMEN:` al inicio de cada uno, y los concatena.

2. Si el tema está en un solo bloque → G0.B = ese RESUMEN.
3. Si el tema está disperso en varios bloques → G0.B = concatenación de
   los RESUMEN de cada bloque, separados por `\n\n---\n\n`.

### 3.4. F4 — Mismo prompt en fallback que en Worker Bun

**Principio**: el subagente de fallback debe usar exactamente el mismo
prompt riguroso (600-900 chars, 4 oraciones) que el Worker Bun.

**Implementación**:

1. **`pipeline.py`**: `_construir_pending_task_para_bloque()` reemplaza el
   prompt genérico por el mismo `PROMPT_RESUMEN` del Worker Bun (importado
   desde `mini-services/worker-cascade/index.ts` o duplicado en Python).

2. Como el prompt vive en TypeScript (Worker Bun), se crea una versión
   Python idéntica en `config.py` como constante `PROMPT_RESUMEN_RIGIDO`.

### 3.5. F5 — Sort global + timestamps válidos + non-chat

**Principio**: el orden cronológico debe mantenerse globalmente dentro de
cada bloque, sin importar de qué tema venga cada intercambio. Además, los
timestamps deben validarse (no 0) y el sistema debe funcionar cuando no
hay cronología (documentación externa).

**Implementación**:

1. **`processing/block_packer.py`**: al final de `pack()`, antes de devolver
   los bloques, ordenar los intercambios de cada bloque por `start_timestamp`
   globalmente (no por tema). Esto garantiza que dentro de cada bloque, los
   intercambios estén en orden cronológico sin importar su tema.

2. **`models.py`**: `ThematicBlock.period_str` valida que `end_timestamp`
   no sea 0. Si es 0, usa `start_timestamp` como fallback.

3. **`models.py`**: `Exchange.end_datetime` valida que `end_timestamp` no
   sea 0. Si es 0, usa `start_timestamp` (no `director_msg.timestamp` que
   puede ser posterior).

4. **Soporte non-chat**: `Exchange.start_timestamp` y `end_timestamp`
   se inicializan a `0.0`. Cuando no hay cronología (docs externos), el
   sort por `start_timestamp` es estable (todos tienen 0.0) y no rompe.

## 4. Lo que se conserva de v6.3

- Worker Bun v6.3 con cascada W1→W2, backoff, cache, modelo dual.
- Fallback al agente con subagentes (v6.2).
- `_ejecutar_pending_tasks_obligatorias()` (v6.3 F1).
- `ThematicBlock.tiene_resumen()` (v6.2).
- `_incluir_bloques_anteriores()` (v6.3 F2).
- Sort cronológico en `ExchangeBuilder` (v6.3 F4).
- Prompt riguroso en Worker Bun (v6.3 F5).
- 4 archivos de recuperación (00, 01, 02, 03).
- Constantes v6.3 en `config.py`.

## 5. Lo que se añade en v6.4

- **`pipeline._consolidar_decisiones_llm()`** — lee `_responses/bloque_*_decisiones.txt` y los integra en `02_decisiones_clave.md`.
- **`estado_generator._build_a1()` mejorado** — filtra volcados en `agent_msgs` + aplica `ContentCleaner`.
- **`estado_generator._build_g0_b()` práctico** — lee RESUMEN del bloque del tema activo.
- **`pipeline._construir_pending_task_para_bloque()` con prompt riguroso** — usa el mismo prompt del Worker Bun.
- **`block_packer.pack()` con sort global** — ordena intercambios dentro de cada bloque por timestamp.
- **`models.py` validación de timestamps** — `period_str` y `end_datetime` con fallback.
- **`config.py` PROMPT_RESUMEN_RIGIDO** — versión Python del prompt del Worker Bun.
- **Eliminación de `DecisionExtractor` regex** de `recovery_cycle.py`.

## 6. Lo que se elimina

- `DecisionExtractor` regex como fuente de decisiones (se elimina del flujo).
- Placeholder de G0.B ("Síntesis del contexto no disponible").
- Prompt genérico de `_construir_pending_task_para_bloque()`.

## 7. Reglas de implementación

- Cambios quirúrgicos, OOP, no hardcoding, comentario en primera línea.
- Tests atómicos en `__main__` de cada módulo intervenido.
- 5 tests E2E nuevos en `tests/test_v42_e2e.py`.

## 8. Validación

1. `test_v64_decisiones_consolidadas`: `02_decisiones_clave.md` tiene las decisiones de `_responses/`.
2. `test_v64_a1_sin_tool_calls`: A1 no contiene JSON de `tool_calls`.
3. `test_v64_g0b_con_resumen`: G0.B contiene el RESUMEN del bloque del tema activo.
4. `test_v64_fallback_mismo_prompt`: el prompt del fallback es el mismo del Worker Bun.
5. `test_v64_sort_global`: los intercambios dentro de cada bloque están ordenados globalmente.

---

**Fin de la spec v6.4.**
