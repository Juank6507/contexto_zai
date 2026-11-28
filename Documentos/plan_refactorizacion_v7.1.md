# PLAN — Refactorización v7.1

**Versión:** 7.1
**Fecha:** 2026-11-28
**Estado:** Implementado y validado
**Continuación de:** plan v7.0

---

## Fases

### F1 — Fix F2 (período con timestamps completos)
- **Archivo:** `models.py` `ThematicBlock.period_str`
- **Cambio:** `min(ex.start_datetime for ex in self.exchanges)` + `max(ex.end_datetime for ex in self.exchanges)` + `strftime('%Y-%m-%d %H:%M')`
- **Eliminar:** fallback `if last < first: last = first`
- **Estado:** ✓ Implementado

### F2 — Fix F5 (objetivo vía subagente W3)
- **Archivo:** `generation/estado_generator.py` `_extraer_objetivo_de_bloques()`
- **Cambio:** invocar `CicloW3.ejecutar_subagente_generacion()` con `PROMPT_OBJETIVO_DESDE_RESUMENES`
- **Validador:** `_validar_objetivo_critico` rechaza "Proyecto sobre:" y exige estructura G0.A/G0.B/G0.C
- **Estado:** ✓ Implementado

### F3 — Fix F6 (D4/A3/A4 con LLM)
- **Archivo:** `generation/estado_generator.py` `_build_d4()`, `_build_a3()`, `_build_a4()`
- **Cambio:** rama `if self._launcher is not None` invoca `CicloW3.ejecutar_subagente_generacion()` con prompts `PROMPT_D4_RESTRICCIONES`, `PROMPT_A3_ERRORES`, `PROMPT_A4_INSTRUCCIONES`
- **Estado:** ✓ Implementado

### F4 — Auditoría ampliada
- **Archivo:** `pipeline_auditoria.py` `auditar_workspace_completo()` + `pipeline_d7.py` `despachar_por_tipo()`
- **Cambio:** revisar TODOS los archivos, encolar carencias con campo `tipo`, enrutar al módulo correcto
- **Estado:** ✓ Implementado

### F5 — Fix E4 (escapes en G0.B)
- **Archivo:** `pipeline_archivos.py` `_regenerar_sintesis_contexto()`
- **Cambio:** reemplazar `_re_module.escape(sintesis_text)` por `lambda m: m.group(1) + sintesis_text + "\n"`
- **Estado:** ✓ Implementado (commit `7db0019`)

### F6 — Fix E2/E3 (update_czai.ps1)
- **Archivo:** `update_czai.ps1`
- **E2:** `$env:PYTHONPATH = Split-Path $RutaLocalProyecto -Parent` en `Test-Funcionamiento`
- **E3:** 12 reemplazos de imports a prefijo `contexto_zai.`
- **Estado:** ✓ Implementado

### F7 — Empaquetado completo
- **Incluir:** las 8 carpetas que faltaban (Documentos/, mini-services/, mini-services-externos/, sandbox-src/, tests/, retorno/, scripts/, entregas/)
- **MANIFIESTO:** regenerado con SHA256 real
- **Estado:** ✓ Implementado
