# SPEC — Sistema de Recuperación de Contexto v7.1

**Versión:** 7.1
**Fecha:** 2026-11-28
**Estado:** Implementado y validado
**Continuación de:** spec v7.0

---

## Cambios de v7.0 → v7.1

### F2 — Período del header con timestamps completos

**Problema v7.0:** `ThematicBlock.period_str` usaba `exchanges[0]` y `exchanges[-1]` con fallback `if last < first: last = first`. El fallback se activaba siempre (orden descendente) y producía fechas iguales.

**Fix v7.1:** calcular período con `min(ex.start_datetime)` y `max(ex.end_datetime)` independientes del orden. Formato `YYYY-MM-DD HH:MM -> YYYY-MM-DD HH:MM` (con hora).

### F5 — Objetivo del proyecto vía subagente W3

**Problema v7.0:** `_extraer_objetivo_de_bloques()` generaba "Proyecto sobre: tema1, tema2..." (lista de temas, no objetivo real).

**Fix v7.1:** `_extraer_objetivo_de_bloques()` invoca `CicloW3.ejecutar_subagente_generacion()` con `PROMPT_OBJETIVO_DESDE_RESUMENES` que lee los RESUMENES de los bloques y genera el objetivo real del proyecto. Validado por `_validar_objetivo_critico` que rechaza "Proyecto sobre:" y exige estructura G0.A/G0.B/G0.C/procedimiento.

### F6 — Secciones D4/A3/A4 con subagente LLM

**Problema v7.0:** `_build_d4()`, `_build_a3()`, `_build_a4()` usaban regex con fallback a mensajes vacíos ("No se identifican restricciones explícitas").

**Fix v7.1:** cada `_build_*` tiene rama `if self._launcher is not None` que invoca `CicloW3.ejecutar_subagente_generacion()` con prompts específicos (`PROMPT_D4_RESTRICCIONES`, `PROMPT_A3_ERRORES`, `PROMPT_A4_INSTRUCCIONES`). El subagente lee los intercambios del tema activo y extrae restricciones del Director, errores discutidos e instrucciones emitidas.

### Auditoría ampliada

**Problema v7.0:** `auditar_calidad()` solo revisaba los 4 archivos principales con condiciones específicas. No revisaba contenido de los 22 bloques.

**Fix v7.1:** `auditar_workspace_completo()` revisa TODOS los archivos (4 principales + 22 bloques + _responses + metadata + sincronización). Las carencias detectadas se encolan como pending_tasks con campo `tipo` para que `despachar_por_tipo` en `pipeline_d7.py` las enrute al módulo correcto para reprocesado por el ciclo W3.

### E4 — Escapes literales en G0.B (fix post-validación)

**Problema:** `_regenerar_sintesis_contexto` usaba `_re_module.escape(sintesis_text)` en el reemplazo de `pattern.sub()`, escapando `*` → `\*`, `.` → `\.` en el texto del G0.B.

**Fix:** reemplazar por `lambda m: m.group(1) + sintesis_text + "\n"` (no necesita escape).

### E2/E3 — update_czai.ps1 (fixes de validación Windows)

**E2:** añadir `$env:PYTHONPATH = Split-Path $RutaLocalProyecto -Parent` antes de sentencias de prueba.
**E3:** cambiar imports de sentencias a prefijo `contexto_zai.` para consistencia con código interno.
