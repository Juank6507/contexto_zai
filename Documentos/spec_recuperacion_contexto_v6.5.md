# contexto_zai/Documentos/spec_recuperacion_contexto_v6.5.md
# Spec v6.5 — Preservar bloques externos + estructura canónica + objetivo robusto

**Versión:** 6.5
**Fecha:** 2026-09-30
**Estado:** Implementado.
**Especifica continuación de:** spec v6.4.

## 1. Propósito

La v6.4 corrigió la calidad del contexto. Pero al probar el contexto del agente APA surgieron 4 problemas nuevos.

## 2. Los 4 problemas

| # | Problema | Causa |
|---|---|---|
| 1 | 9 bloques externos vaciados (35 bytes) | RecoveryCycle sobrescribe todos los archivos del workspace |
| 2 | Bloques no homogéneos (formato y nombres distintos) | No hay estructura canónica ni normalización de nombres |
| 3 | 03_objetivo_proyecto.md incompleto + typo | El proceso no sobrescribe si ya existe (aunque esté mal) |
| 4 | Índice muestra ~? en tokens de bloques externos | IndiceGenerator no encuentra bloques externos |

## 3. Soluciones

### F1 — Preservar bloques externos en RecoveryCycle
- `process/recovery_cycle.py`: `_write_files()` NO sobrescribe archivos `bloque_externo_*` preexistentes que no estén en la lista de `recovery_files`.

### F2 — Estructura canónica de bloques
- `pipeline.py`: `_normalizar_bloques_externos()` renombra `bloque_externo_grande_*` a `bloque_NN.md` con el siguiente número disponible, y actualiza `_metadata.json` y `_pending_blocks.json`.
- `generation/bloque_generator.py`: ya genera formato canónico `# Bloque tematico: <tema>` (verificado).

### F3 — 03_objetivo_proyecto.md se sobrescribe si incompleto
- `generation/estado_generator.py`: `_asegurar_objetivo_proyecto()` sobrescribe si < 500 bytes o no contiene "## Quién eres".

### F4 — IndiceGenerator incluye bloques externos en tokens
- `generation/indice_generator.py`: `_find_tokens_for_tema()` busca en workspace si no encuentra en blocks.

---

**Fin de la spec v6.5.**
