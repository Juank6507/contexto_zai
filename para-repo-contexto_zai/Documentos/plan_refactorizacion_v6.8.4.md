# contexto_zai/Documentos/plan_refactorizacion_v6.8.4.md
# Plan v6.8.4 — Eliminar temas provisionales + regenerar índice tras enriquecimiento

**Versión:** 6.8.4
**Fecha:** 2026-10-07
**Estado:** Pendiente.
**Continuación de:** plan v6.8.3.
**Spec asociada:** spec_recuperacion_contexto_v6.8.4.md

## Objetivo

Eliminar los temas provisionales del metadata y regenerar el índice después
del enriquecimiento, sin tocar lo que ya funciona.

## Principio: proteger lo existente

Lo que ya funciona NO se toca.

## Fases

### F1 — No crear temas provisionales al integrar bloques

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. En `_integrar_documento()`, eliminar el bloque que registra temas
   provisionales (`documento_externo_N`) en `tema_a_archivo`.
2. El bloque se sigue escribiendo al disco con su nombre `bloque_NN.md`.
3. El bloque se sigue registrando en `archivo_a_source` (procedencia).
4. No se registra nada en `tema_a_archivo` — el enriquecimiento lo hará
   después.
5. El índice se sigue regenerando, pero solo mostrará bloques que ya
   tengan tema (los del chat o los ya enriquecidos).

**Lo que NO se toca:**
- Escritura del bloque físico.
- Registro en `archivo_a_source`.
- Header canónico del bloque.
- Contenido literal del bloque.

**Tests con datos reales:**
- Documento APA procesado → verificar que `tema_a_archivo` está vacío
  para el bloque nuevo, pero `archivo_a_source` lo tiene.
- `query_context` no encuentra el bloque por tema (correcto).
- El bloque físico existe y tiene contenido literal.

### F2 — Regenerar el índice después del enriquecimiento

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. En `collect_responses()`, después de que `_enriquecer_bloques_con_fallback()`
   termina (y los bloques tienen RESUMEN y temas enriquecidos), invocar
   la regeneración del índice.
2. Leer el metadata actualizado (que ahora tiene los temas reales).
3. Regenerar `01_indice_recuperacion.md` con los temas reales.
4. Los bloques sin tema (los que no se enriquecieron o no tienen
   clasificación) no aparecen en el índice.

**Lo que NO se toca:**
- El enriquecimiento en sí (Worker Bun o subagentes).
- Los bloques físicos.
- Las pending_tasks.

**Tests con datos reales:**
- Documento APA procesado + enriquecimiento simulado → verificar que el
  índice tiene los temas reales y no los provisionales.

### F3 — _normalizar_bloques_externos elimina provisionales residuales

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En `_normalizar_bloques_externos()`, después de limpiar prefijos,
   buscar temas que empiecen con `documento_externo_` o `grande_ampliar_`.
2. Si el bloque al que apuntan ya tiene otros temas enriquecidos en
   `tema_a_archivo`, eliminar el provisional.
3. Si el bloque no tiene otros temas (no fue enriquecido), mantener el
   provisional temporalmente.

**Tests con datos reales:**
- Metadata con mezcla de provisionales y enriquecidos → después de
  normalizar, los provisionales se eliminan cuando hay enriquecidos.

### F4 — Actualizar tests

**Archivos:** `tests/test_v42_e2e.py`, `coordinador/integrador_respuestas.py` (__main__).

**Qué se hace:**
1. Tests del integrador: verificar que no hay temas provisionales en
   `tema_a_archivo` después de integrar un documento.
2. Tests E2E: verificar que `query_context` no encuentra bloques sin
   tema (correcto: no deberían aparecer hasta que se enriquezcan).
3. Tests E2E: verificar que después del enriquecimiento, el índice se
   regenera con los temas reales.

### F5 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos.
2. Ejecutar los 30+ tests E2E.
3. Validar con datos reales que:
   - No hay temas provisionales en el metadata.
   - No hay prefijos `grande_ampliar_` en el metadata.
   - El índice tiene solo temas reales.
   - Los bloques siguen teniendo RESUMEN y contenido literal.
   - Las pending_tasks siguen funcionando.

---

**Fin del plan v6.8.4.**
