# contexto_zai/Documentos/spec_recuperacion_contexto_v6.14.md
# Spec v6.14 — Reorganación del pipeline a 19 pasos + daemon + detonante

**Versión:** 6.14
**Fecha:** 2026-11-07
**Estado:** Pendiente de implementación.
**Especifica continuación de:** spec v6.13.
**Sesión origen:** CZAI 6a00fcb8, elemento C del método DCEPI (conciliación con el Director).
**Informe de referencia:** `download/informe_conciliacion_detonante_falta_contexto.md` (para el agente EP).

---

## 1. Propósito

Corregir los problemas detectados en la iteración 1 del Gauntlet v6.13 tras su ejecución sobre datos reales del chat `6a00fcb8`. La iteración 1 no pasó el criterio C14 (Gauntlet 100% datos reales) por errores de implementación que esta spec aborda.

Problemas detectados en v6.13 (iteración 1):

1. **P16 mal posicionado:** la auditoría final (`AuditorWorkspace.auditar_completitud`) corre dentro de `orch.activate()` ANTES del enriquecimiento (P14), en vez de después. Reporta "N incompletos" porque los bloques aún no se han enriquecido.
2. **`_ejecutar_pending_tasks_obligatorias()` no es un bucle D7:** intenta resolver pending_tasks llamando `collect_responses()`, que es la herramienta de búsqueda (`query_context`), no la de completitud. No hay reintentos con feedback.
3. **Tres piezas mezcladas en el código:** `_pending_tasks` (saco de deudas), bucle D7 (garantía de completitud) y `collect_responses()` (colector de búsqueda) están mezcladas, lo que llevó al agente a confundir las pending_tasks de extracción con las de enriquecimiento.
4. **Falta el daemon del proceso:** no hay mini-servicio siempre corriendo. El proceso se lanza por scripts invocados manualmente por el agente CZAI (`runner_ampliar.py`, `runner_collect.py`, `enrich_nivel2.py`), lo que mezcla roles y viola el modo de ejecución v1.6 (un Actuador + Crítico).
5. **Falta el detonante de falta de contexto:** la premisa de respuesta no es explícita sobre qué hacer cuando el agente no puede emitir la frase de control. Se ha producido un informe al agente EP para documentar la conciliación en `premisa_respuesta.md` §3 y `herramientas.md` §8.
6. **`ampliar_contexto` no determina estructura del contenido:** no distingue exchanges cronológicos (procesar como chat de Z.ai) de documentos arbitrarios (saltar P5 directamente a P6).
7. **Bloques externos mal clasificados:** los bloques de fuente externa (P4.2) se generan con cabecera `# Bloque temático: documento_externo_N` en vez de una cabecera que distinga su origen y conserve el orden de entrada.

---

## 2. Orden del proceso (19 pasos, reorganización de v6.13)

1. Cargar JWT del CredentialManager.
2. **Auditoría integral al arrancar** (AuditorWorkspace: buscar `contexto_recuperacion/`, auditar bloques + enriquecimiento + metadata). **Lo incorrecto/incompleto se vierte al saco `_pending_tasks.json`.**
3. Decidir recovery vs incremental según auditoría:
   - Caso A (primera vez, sin metadata) → RecoveryCycle.
   - Caso B (mismo chat que la metadata existente) → IncrementalCycle.
   - Caso C (metadata de OTRO chat distinto) → **borrar la carpeta completa `contexto_recuperacion/`** y RecoveryCycle.
4.1 Extraer mensajes (chat cronológico de Z.ai: árbol + batch paginado).
4.2 **Determinar estructura del contenido** (solo `ampliar_contexto`): si el contenido son exchanges cronológicos → procesar como P4.1 (extraer y construir intercambios en P5); si NO son exchanges cronológicos → saltar directamente a P6.
5. Construir intercambios (ExchangeBuilder) — solo si cronológico (P4.1).
6. Clasificar por tema (MessageClassifier):
   - Si P4.1: etiqueta cada intercambio individual con un tema.
   - Si P4.2: analiza el bloque completo y extrae los temas que contiene.
7. Empaquetar bloques cronológicos descendentes (BlockPacker): bloques de P4.1 ordenados por timestamp descendente (bloque_01 = más nuevo); **bloques de P4.2 agrupados al final en el orden de entrada al contexto**.
8. Escribir bloques físicos (BloqueGenerator): cabecera distinta según origen:
   - P4.1 → `# Bloque cronológico N`.
   - P4.2 → `# Bloque externo N` (con `**Source:** ampliar_contexto`).
9. Generar `00_estado_actual.md` (EstadoGenerator) — **solo si el contenido es cronológico (P4.1)**. Si viene de P4.2, NO se genera.
10. Generar `01_indice_recuperacion.md` (IndiceGenerator).
11. Generar `02_decisiones_clave.md` (DecisionesGenerator).
12. Generar `03_objetivo_proyecto.md`.
13. Escribir `_metadata.json` (con `tema_a_archivo`).
14. **Enriquecimiento (cascada W1+W2+W3 con bucle D7 en cada nivel):**
    - Nivel 1 (Worker Bun): arranca una vez, procesa en paralelo (lotes de 5). Reintenta con D7 (modificar prompt → re-entregar al Actuador → re-valorar como Crítico → re-probar) hasta MAX_ITER=5. Si no completa → Nivel 2.
    - Nivel 2 (Proxy Z.ai directo con `PROMPT_FUSIONADO_W1W2W3`): procesa los restantes uno por uno. Bucle D7 con MAX_ITER_W3=5 (feedback al LLM, backoff 429 sin consumir MAX_ITER). Si no completa → Nivel 3.
    - Nivel 3 (Subagentes del agente CZAI): **publica `_pending_tasks.json` y NO las ejecuta** — las deja para P17. **Ante cada nueva tarea o lote de tareas se vuelve a intentar desde Nivel 1.**
15. Sincronizar `_processed_blocks.json` (AuditorWorkspace.sincronizar_registro).
16. **Auditoría final** (AuditorWorkspace.auditar_completitud) — **después del enriquecimiento P14**. Lo que siga incompleto se vierte al saco `_pending_tasks.json`.
17. **Bucle D7: regenerar/completar lo faltante con garantía de completitud.** El agente CZAI (como Crítico) lee `_pending_tasks.json` (el saco) y para cada bloque incompleto ejecuta:
    1. Revisar la falla respecto a lo conciliado en la spec.
    2. Modificar el prompt corrigiendo esa falla.
    3. Re-entregarlo al Actuador (subagente del Task tool).
    4. Re-valorar como Crítico contra el baremo (W3 validación: 600-900 chars, 4 oraciones, sin etiquetas).
    5. Re-probar.
    6. Si pasa → fuera del saco. Si no → próxima iteración.
    - Máximo 5 intentos (MAX_ITER=5). Si se agotan → informe al Director con las 4 preguntas por iteración (qué falló → qué se diagnosticó → cómo se corrigió → qué se implementó).
18. Consolidar decisiones LLM (de `_responses/bloque_NN_decisiones.txt` a `02_decisiones_clave.md`).
19. Regenerar índice tras enriquecimiento (`01_indice_recuperacion.md`).

---

## 3. Decisiones conciliadas por categoría

### Categoría 1 — Reorganación del pipeline (3 problemas)

| # | Problema | Decisión |
|---|---|---|
| 1 | P16 mal posicionado (dentro de `orch.activate()`, antes de P14) | Reposicionar P16 después de P14. La auditoría final debe verificar el estado real tras el enriquecimiento, no antes. |
| 2 | `_ejecutar_pending_tasks_obligatorias()` no es un bucle D7 | Sustituir por un bucle D7 real en P17: revisar falla → modificar prompt → re-entregar al Actuador → re-valorar como Crítico → re-probar, hasta MAX_ITER=5 |
| 3 | Tres piezas con roles mal delimitados en el código | Clarificar los tres roles distintos: (1) `_pending_tasks.json` es el saco de deudas (se llena en P2, P14, P16); (2) el bucle D7 en P17 vacía el saco con reintentos con feedback hasta MAX_ITER=5; (3) `collect_responses()` es el integrador de respuestas de subagentes (cualquier propósito) Y dispara la cascada P14 cuando quedan bloques sin RESUMEN. **El problema no es que estén mezcladas, es que `_ejecutar_pending_tasks_obligatorias()` invoca `collect_responses()` como si fuera un bucle D7** — lo llama como "arregla todo" sin reintentos con feedback. La corrección: sustituir esa llamada por el bucle D7 real de P17, manteniendo `collect_responses()` en su rol correcto dentro del flujo P14-P17. |

### Categoría 2 — Daemon y detonante (2 problemas)

| # | Problema | Decisión |
|---|---|---|
| 4 | Falta el daemon del proceso | Crear mini-servicio `pipeline-daemon` siempre corriendo (puerto a determinar, p. ej. 8088). El daemon escucha órdenes y ejecuta la API pública (`ampliar_contexto`, `pipeline.run`). El agente CZAI solo invoca la API pública; no escribe scripts runner_*.py |
| 5 | Falta el detonante de falta de contexto | Documentado en el informe al agente EP (`download/informe_conciliacion_detonante_falta_contexto.md`). La premisa de respuesta debe ser explícita: cuando el agente no pueda emitir la frase de control → invocar al daemon del proceso contexto_zai vía `ampliar_contexto(chat_id_actual)` modo INCREMENTAL → leer los 4 archivos de recuperación (03_objetivo_proyecto, 00_estado_actual, 01_indice_recuperacion, 02_decisiones_clave) → reemitir frase de control |

### Categoría 3 — ampliar_contexto y bloques externos (3 problemas)

| # | Problema | Decisión |
|---|---|---|
| 6 | `ampliar_contexto` no determina estructura del contenido | P4.2 determina: si el contenido son exchanges cronológicos (formato con `## Exchange N -- [timestamp]`) → procesar como P4.1 (extraer y construir intercambios en P5); si NO son exchanges cronológicos → saltar directamente a P6 |
| 7 | Bloques externos mal clasificados | Cabecera distinta según origen: P4.1 → `# Bloque cronológico N`; P4.2 → `# Bloque externo N` (con `**Source:** ampliar_contexto`) |
| 8 | 00_estado_actual.md se genera para fuentes externas | P9 solo se ejecuta si el contenido es cronológico (P4.1). Si viene de P4.2, NO se genera 00_estado_actual.md |

### Categoría 4 — Ordenamiento de bloques (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 9 | Bloques externos se mezclan con cronológicos | P7: bloques de P4.1 ordenados por timestamp descendente (bloque_01 = más nuevo); bloques de P4.2 agrupados al final en el orden de entrada al contexto que se está generando |

### Categoría 5 — Pendientes de v6.13 (1 problema)

| # | Problema | Decisión |
|---|---|---|
| 10 | Cambios v6.13 sin commitear (MAX_ITER_W3, _validar_resumen_w3, backoff 429) | Commitear como parte de v6.14 antes de la reorganación, para preservar la trazabilidad |

---

## 4. Baremo táctico derivado del estratégico

### Gauntlet (7 pasos con datos reales, sin cambios respecto a v6.13)

| Paso | Verificación | Umbral |
|---|---|---|
| 1 | Inicio: proceso arranca sobre workspace | workspace con bloques + metadata |
| 2 | Auditoría de bloques existentes | AuditorWorkspace.auditar_completitud() |
| 3 | 1er bloque (más actual) | bloque_01 = max(timestamp) si P4.1; bloque_01 = primer bloque externo si P4.2 |
| 4 | 5 próximos bloques | orden descendente verificado (P4.1) u orden de entrada (P4.2) |
| 5 | 5 últimos bloques | bloques más viejos verificados |
| 6 | Auditoría de cierre | _processed_blocks.json sincronizado |
| 7 | Ficheros 00-03 | 4 archivos generados por el proceso (00_estado_actual solo si cronológico) |

### Criterios de aceptación (10 nuevos + 16 heredados de v6.13 = 26)

**Heredados de v6.13 (16):**
1. BlockPacker genera bloques cronológicos descendentes. Cabecera `# Bloque cronológico N`.
2. PROGRESS_GROWTH=2.0.
3. _processed_blocks.json coincide con estado físico.
4. Auditoría integral al arrancar (AuditorWorkspace integrado en Orchestrator.activate()).
5. ProgressMonitor orquesta cascada. Nunca se detiene.
6. Proxy Z.ai pasa headers X-Ratelimit-*.
7. Cascada nunca se detiene (no hay pausa de 10 min).
8. W1+W2+W3 fusionados en 1 llamada.
9. Lotes de 5 en paralelo.
10. Validación ajena al ejecutor (W3). MAX_ITER=5.
11. 0 menciones "proxy APA".
12. .zip incluye todo el contenido.
13. update_czai.ps1 respeta plantilla v1.5.4.
14. Gauntlet 7 pasos pasa 100% con datos reales.
15. Ficheros 00-03 generados por el proceso.
16. Contexto reconstruido desde exchanges_czai_consolidados.md.

**Nuevos de v6.14 (10):**

17. P16 (auditoría final) corre después de P14 (enriquecimiento), no dentro de `orch.activate()` antes del enriquecimiento.
18. P17 implementa bucle D7 con MAX_ITER=5: revisar falla → modificar prompt → re-entregar al Actuador → re-valorar como Crítico → re-probar.
19. `_ejecutar_pending_tasks_obligatorias()` ya no invoca `collect_responses()` como "arregla todo"; la sustituye el bucle D7 de P17. `collect_responses()` se mantiene en su rol correcto dentro del flujo P14-P17 como integrador de respuestas + disparador de la cascada.
20. Existe mini-servicio `pipeline-daemon` siempre corriendo (puerto escuchando, no script invocado manualmente).
21. El agente CZAI no escribe scripts `runner_*.py` para invocar el proceso; usa la API pública del daemon.
22. `ampliar_contexto` determina estructura del contenido (P4.2): exchanges cronológicos → P5; documento arbitrario → P6 directo.
23. Bloques externos (P4.2) se generan con cabecera `# Bloque externo N` (no `# Bloque temático:`).
24. `00_estado_actual.md` solo se genera si el contenido es cronológico (P4.1).
25. Bloques de P4.2 se ordenan al final del workspace, después de los cronológicos, en orden de entrada.
26. Cambios v6.13 (MAX_ITER_W3, _validar_resumen_w3, backoff 429) commiteados antes de la reorganación de v6.14.

---

**Fin de la spec v6.14.**
