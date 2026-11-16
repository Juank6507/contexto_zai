# contexto_zai/Documentos/plan_refactorizacion_v6.19.md
# Plan v6.19 — Fixes de los 8 problemas de v6.18

**Versión:** 6.19
**Fecha:** 2026-11-15
**Estado:** Implementado (Gauntlet NH27 verde).
**Spec asociada:** spec_recuperacion_contexto_v6.19.md

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico.

---

## Fases

### F1 — chat_id siempre del chat actual (P1, P5)

- **Archivos:** `contexto_zai/pipeline.py`, `contexto_zai/generation/estado_generator.py`, `contexto_zai/generation/recovery_generator.py`, `contexto_zai/process/recovery_cycle.py`, `mini-services/pipeline-daemon/index.py`
- **Cambio:**
  - `ampliar_contexto()` recibe `chat_id` como parámetro.
  - El daemon pasa `chat_id` desde los metadatos del gateway IM.
  - `RecoveryCycle` propaga `chat_id` a `RecoveryGenerator` y `EstadoGenerator`.
  - `EstadoGenerator.generate()` usa `chat_id` en la cabecera.
  - `_metadata.json` tiene `chat_id` poblado.
- **Estado:** ✅ Implementado
- **Criterio de aceptación:** 1 y 2.

### F2 — Parser A2/A3 omite bloques bash (P2)

- **Archivos:** `contexto_zai/generation/estado_generator.py`
- **Cambio:**
  - Nuevo método `_strip_bash_blocks(content)` que elimina bloques ` ```bash ... ``` ` (también python, cmd, sh, etc.).
  - Aplicado en `_build_a2` y `_build_a3` antes del regex de detección.
  - Encadenado con `_strip_tool_calls` existente.
- **Estado:** ✅ Implementado
- **Criterio de aceptación:** 3.

### F3 — Marcar errores como históricos (P3, P8)

- **Archivos:** `contexto_zai/generation/estado_generator.py`
- **Cambio:**
  - Nuevo método `_obtener_timestamp_workspace()` que lee `_metadata.json["ultimo_timestamp"]`.
  - En `_build_a3`, cada error se anota con `[histórico YYYY-MM-DD]` si su antigüedad > 7 días.
  - Los RESUMENES de bloques NO se censuran.
- **Estado:** ✅ Implementado
- **Dependencias:** F2.
- **Criterio de aceptación:** parcial (marcado histórico).

### F4 — `_asegurar_objetivo_proyecto()` lee el worklog canónico (P4)

- **Archivos:** `contexto_zai/generation/estado_generator.py`
- **Cambio:**
  - Nuevo método `_extraer_objetivo_de_worklog(project_root)`.
  - Lee `/home/z/my-project/worklog.md`.
  - Parsea cabecera para obtener agente + proyecto.
  - Genera 4 secciones con placeholders `__MODELO_AGENTE__`, `__ACTA_NACIMIENTO__`, `__DIRECTOR__`, `__EMAIL__`.
  - Métodos auxiliares `_extraer_sesiones_worklog`, `_extraer_evolucion_worklog`.
  - `_extraer_objetivo_de_documentacion` queda deprecated pero se mantiene por compatibilidad.
  - El archivo se genera **una sola vez**.
- **Estado:** ✅ Implementado
- **Criterio de aceptación:** 4.

### F5 — Hash SHA256 para detectar fuente cambiada (P6, P7)

- **Archivos:** `contexto_zai/pipeline.py`
- **Cambio:**
  - En `ampliar_contexto`, antes de llamar a `RecoveryCycle`:
    1. Calcular `sha256(content_bytes)`.
    2. Leer `source_sha256` de `_metadata.json`.
    3. Si difieren, eliminar todos los `bloque_*.md` antes de regenerar.
    4. Tras generar, escribir el hash actual en `_metadata.json["source_sha256"]`.
  - Aplica a ambos flujos: cronológico (RecoveryCycle) y arbitrario (ProcesadorDocumento).
- **Estado:** ✅ Implementado
- **Criterio de aceptación:** 5.

### F6 — Tests + validación con datos reales

- **Qué se hace:**
  1. Gauntlet determinista I.2 (6 fases): ✅ Pasó
  2. Gauntlet NH27 con datos reales sobre `exchanges_small.md` (1500 líneas del consolidado): ✅ Pasó (5/5 criterios)
- **Estado:** ✅ Completado
- **Dependencias:** F1-F5.

### F7 — Gauntlet de terminación

- **Qué se hace:**
  1. Gauntlet determinista: ✅ verde
  2. Gauntlet NH27 con datos reales: ✅ verde (iteración D7=2)
  3. Veredicto JSON: ✅ aprobado
- **Estado:** ✅ Completado
- **Dependencias:** F6.

---

## Orden de ejecución

| Fase | Descripción | Deps | Estado |
|---|---|---|---|
| F1 | chat_id siempre del chat actual | ninguna | ✅ |
| F2 | Parser A2/A3 omite bloques bash | ninguna | ✅ |
| F3 | Marcar errores como históricos | F2 | ✅ |
| F4 | `_asegurar_objetivo_proyecto` lee worklog | ninguna | ✅ |
| F5 | Hash SHA256 para detectar fuente cambiada | ninguna | ✅ |
| F6 | Tests + validación con datos reales | F1-F5 | ✅ |
| F7 | Gauntlet de terminación | F6 | ✅ |

---

## Iteración D7 (auto-corrección)

**Iteración 1:** 3/5 criterios pasaron (2, 3, 5). Fallaron:
- Criterio 1: cabecera mostraba nombre archivo en vez de chat_id.
- Criterio 4: 03 no se generaba (EstadoGenerator no recibía chat_id, workspace_dir).

**Corrección:**
- `EstadoGenerator.__init__` acepta `chat_id` param.
- `EstadoGenerator.generate()` usa `chat_id` en cabecera si está disponible.
- `RecoveryGenerator.__init__` acepta `chat_id` y lo pasa al `EstadoGenerator`.
- `RecoveryCycle` propaga `self._chat_id` a `RecoveryGenerator` y `EstadoGenerator`.

**Iteración 2:** 5/5 criterios pasan. ✅ Veredicto verde.

---

**Fin del plan v6.19.**
