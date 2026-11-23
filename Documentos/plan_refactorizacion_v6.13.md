# contexto_zai/Documentos/plan_refactorizacion_v6.13.md
# Plan v6.13 — Corrección de 21 problemas (cambios quirúrgicos, NH18)

**Versión:** 6.13
**Fecha:** 2026-11-06
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.13.md

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

---

## Fases (quirúrgicas, integradas en el flujo del proceso)

### F1 — BlockPacker cronológico descendente (YA hecho, verificar)
- **Archivo:** `processing/block_packer.py`
- **Cambio:** `pack()` ordena por timestamp descendente en vez de agrupar por tema. Los intercambios conservan su tema (para indexación).
- **Estado:** ✅ Implementado

### F2 — Cabecera `# Bloque cronológico N` (YA hecho, verificar)
- **Archivo:** `generation/bloque_generator.py`
- **Cambio:** cabecera cambia de `# Bloque tematico: <temas>` a `# Bloque cronológico N`. Mantiene línea `**Temas en este archivo:**` para indexación.
- **Estado:** ✅ Implementado

### F3 — Constantes PROGRESS_* (YA hecho, verificar)
- **Archivo:** `config.py`
- **Cambio:** PROGRESS_GROWTH=2.0. Comentario justificado.
- **Estado:** ✅ Implementado

### F4 — Renombrado proxy APA → proxy Z.ai (YA hecho, verificar)
- **Archivos:** config.py, pipeline.py, tests/test_v42_e2e.py
- **Cambio:** 0 menciones de "proxy APA" en .py
- **Estado:** ✅ Implementado

### F5 — Proxy pasa headers X-Ratelimit-* (YA hecho, verificar)
- **Archivo:** sandbox-src/api/zai-proxy/_lib.ts
- **Cambio:** respHeaders copia headers X-Ratelimit-* del upstream
- **Estado:** ✅ Implementado

### F6 — AuditorWorkspace integrado en Orchestrator.activate() (NO hecho)
- **Archivos:** pipeline.py, process/orchestrator.py
- **Cambio quirúrgico:**
  - Añadir llamada a `AuditorWorkspace.auditar_completitud(workspace_dir)` al inicio de `Orchestrator.activate()`, antes de decidir recovery vs incremental.
  - Si auditoría encuentra contexto previo del mismo chat → `IncrementalCycle`.
  - Si no → `RecoveryCycle`.
  - Añadir llamada a `AuditorWorkspace.sincronizar_registro(workspace_dir)` antes de devolver el OrchestratorResult.
  - Añadir llamada a `AuditorWorkspace.auditar_completitud(workspace_dir)` al final del flujo (auditoría final).
- **Estado:** ❌ Pendiente

### F7 — PROMPT_FUSIONADO_W1W2W3 integrado en _enriquecer_con_proxy_zai (parcial)
- **Archivo:** pipeline.py
- **Cambio quirúrgico:**
  - `_enriquecer_con_proxy_zai` ya usa `PROMPT_FUSIONADO_W1W2W3` (hecho).
  - Verificar que escribe los 4 artefactos (RESUMEN + 3 archivos) en 1 llamada.
  - Verificar que W3 verifica completitud.
- **Estado:** ✅ Implementado (verificar)

### F8 — _enriquecer_bloques_con_fallback: cascada nunca se detiene (YA hecho, verificar)
- **Archivo:** pipeline.py
- **Cambio:** Worker Bun (1 vez) → proxy Z.ai (1 por 1) → subagentes. Si proxy_ok=False → directo a subagentes. Nunca pausa.
- **Estado:** ✅ Implementado

### F9 — .zip incluye todo el contenido (YA hecho, verificar)
- **Cambio:** .zip incluye Documentos/ + sandbox-src/ + scripts/ + mini-services/
- **Estado:** ✅ Implementado

### F10 — update_czai.ps1 desde plantilla v1.5.4 (YA hecho, verificar)
- **Cambio:** instanciado desde plantilla v1.5.4 con 12 pasos del Director
- **Estado:** ✅ Implementado

### F11 — Ejecutar proceso real + Gauntlet 7 pasos (NO hecho)
- **Qué se hace:**
  1. Ejecutar `ContextoPipeline.run()` sobre el chat 6a00fcb8.
  2. Dejar que el proceso genere los 18 pasos.
  3. Verificar los 7 pasos del Gauntlet sobre lo que el proceso generó.
  4. Si no pasa → corregir y repetir (MAX_ITER=5).
- **Estado:** ❌ Pendiente

### F12 — Reconstrucción del contexto (post-Gauntlet)
- **Qué se hace:**
  1. Crear contexto desde exchanges_czai_consolidados.md.
  2. Actualizar del chat actual.
- **Estado:** ❌ Pendiente (post-Gauntlet)

---

## Orden de ejecución

| Fase | Estado | Dependencias |
|---|---|---|
| F1 BlockPacker cronológico | ✅ | ninguna |
| F2 Cabecera cronológica | ✅ | F1 |
| F3 Constantes PROGRESS_* | ✅ | ninguna |
| F4 Renombrado proxy Z.ai | ✅ | ninguna |
| F5 Proxy headers X-Ratelimit | ✅ | ninguna |
| F6 AuditorWorkspace en Orchestrator | ❌ | ninguna |
| F7 W1+W2+W3 en _enriquecer_con_proxy_zai | ✅ (verificar) | F4 |
| F8 Cascada nunca se detiene | ✅ | F3, F6 |
| F9 .zip completo | ✅ | ninguna |
| F10 update_czai.ps1 | ✅ | F9 |
| F11 Proceso real + Gauntlet | ❌ | F1-F8 |
| F12 Reconstrucción contexto | ❌ | F11 |

**Falta:** F6 (AuditorWorkspace integrado en Orchestrator) y F11 (ejecutar proceso + Gauntlet).

---

**Fin del plan v6.13.**
