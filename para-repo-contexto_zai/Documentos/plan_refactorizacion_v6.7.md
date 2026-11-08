# contexto_zai/Documentos/plan_refactorizacion_v6.7.md
# Plan v6.7 — Bloques con contenido literal + clasificación y enriquecimiento correctos

**Versión:** 6.7
**Fecha:** 2026-10-04
**Estado:** Pendiente.
**Continuación de:** plan v6.6.
**Spec asociada:** spec_recuperacion_contexto_v6.7.md

## Objetivo

Implementar la spec v6.7: corregir el defecto de diseño que viene desde v3.5
donde los bloques externos contienen solo un índice temático (1-2 KB) en vez
del contenido literal formateado hasta 70K tokens. Formalizar los 4 principios
conciliados con el Director en la sesión 21.

## Fases

### F1 — Subagente extractor de contenido literal

**Archivos:** `subagents/documento_indexer_subagent.py`,
`procesadores/procesador_documento.py`.

**Qué se hace:**
1. Cambiar el rol del `DocumentoIndexerSubagent`: de "indexador que genera
   TEMA/DESCRIPCION/RESUMEN" a "extractor que devuelve contenido literal
   formateado en markdown legible".
2. Refactorizar `_build_documento_prompt()` y `_build_lote_prompt()` para
   pedir contenido literal, no índice.
3. El `ProcesadorDocumento` cambia el tamaño de lote: de ~5K tokens a ~70K
   tokens (para llenar el bloque completo).
4. El subagente devuelve el contenido formateado, no un índice.

**Tests:** `__main__` de ambos archivos. Verificar que el prompt pide
contenido literal y el lote es de 70K.

### F2 — Integrador escribe bloque con contenido literal

**Archivos:** `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `_integrar_documento()` deja de escribir el índice como bloque. Pasa el
   contenido literal al `BloqueGenerator` para formato canónico.
2. El bloque se llena hasta 70K con el contenido literal del documento.
3. La clasificación por temas se hace después (Worker 4), no durante la
   extracción.

**Tests:** `__main__` del integrador. Verificar que un documento procesado
genera un bloque de ~70K con contenido literal y header `# Bloque tematico:`.

### F3 — Hook `_debe_generar_recuperacion()` basado en cronología

**Archivos:** `generation/contexto_generator.py`, `pipeline.py`.

**Qué se hace:**
1. Implementar el hook en `ContextoGenerator` con la lógica de los 5 casos
   del Principio 3:
   - `_intercambios_tienen_marca_cronologica()`: verifica timestamps > 0.
   - `_intercambios_son_posteriores_a_ultimo_timestamp()`: compara contra
     `metadata.ultimo_timestamp`.
2. `ampliar_contexto()` pasa a usar `AmpliarGenerator` (clase, no función
   suelta) que hereda de `ContextoGenerator` y respeta el hook.
3. Cuando el hook devuelve False, no se invoca al `EstadoGenerator` ni al
   `DecisionesGenerator` — el estado existente se preserva.

**Tests:** `__main__` de `contexto_generator.py` y `pipeline.py`. Verificar
los 5 casos.

### F4 — Worker 1 (RESUMEN) sobre contenido literal

**Archivos:** `mini-services/worker-cascade/index.ts`, `pipeline.py`.

**Qué se hace:**
1. Confirmar que Worker 1 lee el bloque físico completo (70K con contenido
   literal) y genera el RESUMEN de 600-900 chars.
2. El RESUMEN se escribe al inicio del bloque con prefijo `RESUMEN: `.
3. El `PROMPT_RESUMEN_RIGIDO` ya existe — no se cambia el prompt, solo se
   asegura que el bloque tenga contenido literal.

**Tests:** validación con workspace de prueba. Verificar que el RESUMEN
generado es significativo (describe el contenido real, no un índice).

### F5 — Workers 2-4 sobre el RESUMEN

**Archivos:** `mini-services/worker-cascade/index.ts`, `pipeline.py`.

**Qué se hace:**
1. Workers 2-4 (nombre legible, decisiones, temas) leen solo el RESUMEN al
   inicio del bloque.
2. El Integrador aplica sus respuestas en `_responses/` y actualiza
   `02_decisiones_clave.md` e índice.

**Tests:** validación end-to-end. Verificar que `_responses/` tiene los 4
archivos por bloque y que `02_decisiones_clave.md` se actualiza.

### F6 — EstadoGenerator respeta cronología

**Archivos:** `generation/estado_generator.py`.

**Qué se hace:**
1. Cuando se invoca desde `ContextoGenerator._generar_archivos_recuperacion()`,
   el `EstadoGenerator` usa el último intercambio de la info nueva (no del
   contexto existente).
2. Si la info nueva no es cronológica (caso 5), no se invoca al
   `EstadoGenerator`.

**Tests:** `__main__` de `estado_generator.py`. Verificar que respeta la
cronología.

### F7 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos.
2. Ejecutar los 30 tests E2E de `test_v42_e2e.py`.
3. Validar con el agente APA procesando APA 01/03/04.txt:
   - Bloques externos miden ~70K (no 1-2 KB).
   - Bloques externos empiezan con `RESUMEN: <resumen>`.
   - Bloques externos tienen contenido literal del documento.
   - `00_estado_actual.md` no se genera (APA 01/03/04 no son cronológicos).
4. Validar con un chat real (pipeline.run):
   - Bloques del chat miden ~70K.
   - Bloques del chat empiezan con `RESUMEN: <resumen>`.
   - `00_estado_actual.md` se genera con el último intercambio.

---

**Fin del plan v6.7.**
