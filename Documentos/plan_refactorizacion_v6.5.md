# contexto_zai/Documentos/plan_refactorizacion_v6.5.md
# Plan v6.5 — Preservar bloques externos + estructura canónica + objetivo robusto

**Versión:** 6.5
**Fecha:** 2026-09-30
**Estado:** Implementado.

## F1 — Preservar bloques externos en RecoveryCycle
**Archivo:** `process/recovery_cycle.py`
**Qué:** `_write_files()` preserva `bloque_externo_*` preexistentes no incluidos en recovery_files.
**Test:** 30/30 E2E pasan.

## F2 — Estructura canónica de bloques
**Archivo:** `pipeline.py`
**Qué:** `_normalizar_bloques_externos()` renombra `bloque_externo_*` a `bloque_NN.md` + actualiza metadata + pending_blocks.
**Test:** 30/30 E2E + 9 atómicos pasan.

## F3 — 03_objetivo_proyecto.md se sobrescribe si incompleto
**Archivo:** `generation/estado_generator.py`
**Qué:** `_asegurar_objetivo_proyecto()` sobrescribe si < 500 bytes o sin "## Quién eres".
**Test:** [PASS] estado_generator.py.

## F4 — IndiceGenerator incluye bloques externos en tokens
**Archivo:** `generation/indice_generator.py`
**Qué:** `_find_tokens_for_tema()` busca en workspace + guarda `_workspace_dir_cache`.
**Test:** [PASS] indice_generator.py.

---

**Fin del plan v6.5.**
