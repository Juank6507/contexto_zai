# contexto_zai/Documentos/plan_refactorizacion_v6.6.md
# Plan v6.6 — Unificación OOP de los caminos de generación de contexto

**Versión:** 6.6
**Fecha:** 2026-10-01
**Estado:** Pendiente.
**Continuación de:** plan v6.5.
**Spec asociada:** spec_recuperacion_contexto_v6.6.md

## Objetivo

Implementar la spec v6.6: unificar los dos caminos de generación de contexto
(recuperar del chat y ampliar desde fuente externa) bajo una clase base común
`ContextoGenerator`, con estructura uniforme de bloques, respetando los 4
principios del Director y resolviendo los 9 bugs heredados de v6.5.

## Fases

### F1 — Crear clase base `ContextoGenerator`

**Archivos:** `generation/contexto_generator.py` (nuevo).

**Qué se hace:**
1. Crear `ContextoGenerator` como clase abstracta con el flujo común:
   - `_extraer_intercambios()` (abstracto)
   - `_empaquetar()` (común, usa `BlockPacker`)
   - `_escribir_bloques()` (común, usa `BloqueGenerator` + escribe al disco)
   - `_actualizar_metadata()` (común, usa `MetadataManager`)
   - `_actualizar_indice()` (común, usa `IndiceGenerator`)
   - `_post_procesar()` (común: enriquecer, consolidar decisiones, normalizar)
   - `_debe_generar_recuperacion()` (hook, default True)
   - `_generar_estado()` y `_generar_decisiones()` (solo si el hook es True)
2. El método público `generar()` orquesta la secuencia.

**Tests:** `__main__` del nuevo archivo: verificar que la clase base existe,
es abstracta, y las subclases concretas implementan `_extraer_intercambios()`.

### F2 — Refactorizar `RecoveryCycle` e `IncrementalCycle`

**Archivos:** `process/recovery_cycle.py`, `process/incremental_cycle.py`.

**Qué se hace:**
1. `RecoveryCycle` hereda de `ContextoGenerator`. Sobrescribe
   `_extraer_intercambios()` para extraer todo el chat. `_debe_generar_recuperacion()`
   devuelve `True`.
2. `IncrementalCycle` hereda de `ContextoGenerator`. Sobrescribe
   `_extraer_intercambios()` para extraer solo los nuevos desde `ultimo_timestamp`.
   `_debe_generar_recuperacion()` devuelve `True`.
3. El método `run()` de ambos se simplifica a `return self.generar()`.
4. Se elimina la duplicación: `_regenerar_indice()` (en ambos) se reemplaza
   por `_actualizar_indice()` de la base.

**Tests:** `__main__` de ambos archivos. Los tests existentes deben pasar
sin cambios ( backward compatible con `run()`).

### F3 — Refactorizar `ampliar_contexto()` a `AmpliarGenerator`

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `ampliar_contexto()` (función suelta) se refactoriza a la clase
   `AmpliarGenerator` que hereda de `ContextoGenerator`.
2. Sobrescribe `_extraer_intercambios()` para procesar la fuente externa
   (URL o archivo) vía `ProcesadorDocumento`.
3. `_debe_generar_recuperacion()` devuelve `False` (no genera estado ni
   decisiones, según spec v4.4).
4. Los post-procesamientos (`_enriquecer_bloques_con_fallback`,
   `_consolidar_decisiones_llm`, `_normalizar_bloques_externos`) se
   heredan de la base y se ejecutan.
5. `_integrar_documento()` del `IntegradorRespuestas` se simplifica: deja
   de escribir bloques a mano, pasa por `BloqueGenerator`.

**Tests:** `__main__` de `pipeline.py`. El test de `ampliar_contexto()`
debe seguir pasando.

### F4 — Estructura uniforme de bloques

**Archivos:** `coordinador/integrador_respuestas.py`, `generation/bloque_generator.py`.

**Qué se hace:**
1. Los bloques externos se nombran `bloque_NN.md` desde el principio. El
   número se asigna al momento de escribir, no en un post-procesamiento.
2. Los bloques externos se guardan en la raíz del workspace, no en
   subcarpeta `bloques_externos/`.
3. El header pasa a ser `# Bloque tematico: <temas>` (generado por
   `BloqueGenerator`), no `# Bloque externo: <nombre> (lote N)`.
4. Los bloques externos pasan por `_enriquecer_bloques_con_fallback()`
   para tener `RESUMEN:` al inicio.

**Tests:** `__main__` de `integrador_respuestas.py`. Verificar que un
documento externo procesado genera `bloque_NN.md` con header canónico y
`RESUMEN:` al inicio.

### F5 — Estado correcto en incremental (Bug 11)

**Archivos:** `process/incremental_cycle.py`.

**Qué se hace:**
1. Tras el reempaquetado selectivo, `IncrementalCycle` invoca
   `EstadoGenerator.generate(all_exchanges)` y escribe `00_estado_actual.md`.
2. Invoca `DecisionesGenerator.generate(all_exchanges)` y escribe
   `02_decisiones_clave.md`.
3. Escribe los bloques físicos al disco (hoy los genera en memoria y no
   los persiste — eso causa que el estado y el metadata queden
   desincronizados).

**Tests:** `__main__` de `incremental_cycle.py`. Verificar que tras un
incremental, `00_estado_actual.md` refleja el último intercambio.

### F6 — Índice abarcador (Bugs 1, 2, 5, 6)

**Archivos:** `generation/indice_generator.py`, `models.py`.

**Qué se hace:**
1. `_find_tokens_for_tema()` arreglado: el fallback busca `bloque_*.md`
   en la raíz del workspace, no `bloque_externo_*` en subcarpeta. Estima
   tokens del tamaño del archivo físico.
2. Los `ThematicBlock` del índice se construyen con `temas` y
   `external_size_chars` poblados (no con el hack `block._temas = ...`).
3. Se elimina la sección "Scripts versionados (v3.3)" que referencia
   `_grafos_cambios.json` inexistente (Bug 5).
4. El detector de scripts versionados se amplía: detecta también temas
   cuyos bloques contienen código con extensión de archivo (Bug 6).
5. Se elimina la sección "Documentos indexados (v3.5)" para fuentes
   externas (no aplica).

**Tests:** `__main__` de `indice_generator.py`. Verificar que:
- El índice no contiene `_grafos_cambios.json`.
- Los tokens se muestran correctamente (no `~?`).
- Temas con código se detectan como scripts versionados.

### F7 — Bug 10 (doble prefijo `ampliar_ampliar_`)

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En `ampliar_contexto()` (o `AmpliarGenerator`), se elimina el prefijo
   duplicado. El `filename` entrante ya trae `ampliar_` (por algún paso
   previo), no se le agrega otro.

**Tests:** `__main__` de `pipeline.py`. Verificar que el archivo temporal
se llama `ampliar_APA_01.txt`, no `ampliar_ampliar_APA_01.txt`.

### F8 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos (deben pasar sin cambios).
2. Ejecutar los 30 tests E2E de `test_v42_e2e.py`.
3. Validar con un workspace de prueba que:
   - `pipeline.run()` (recovery) genera los 4 archivos.
   - `pipeline.run()` (incremental, mismo chat) regenera estado + bloques.
   - `ampliar_contexto()` genera bloques con estructura canónica, sin
     estado ni decisiones.
4. Validar que los 9 bugs están resueltos:
   - Bloques externos con `RESUMEN:` (Bug 7).
   - Nombres `bloque_NN.md` (Bug 8).
   - Header `# Bloque tematico:` (Bug 9).
   - Tokens correctos en índice (Bug 2).
   - Sin `_grafos_cambios.json` (Bug 5).
   - Sin doble prefijo (Bug 10).
   - Estado actualizado tras incremental (Bug 11).

---

**Fin del plan v6.6.**
