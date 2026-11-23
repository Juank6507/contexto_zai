# contexto_zai/Documentos/plan_refactorizacion_v6.18.md
# Plan v6.18 — Orquestación del flujo ampliar_contexto + RecoveryCycle + BlockPacker

**Versión:** 6.18
**Fecha:** 2026-11-13
**Estado:** Pendiente de implementación.
**Spec asociada:** spec_recuperacion_contexto_v6.18.md

---

## Principio: cambios quirúrgicos (NH18), validar antes de entregar (NH19), solo lo pedido (NH23)

Modo de ejecución v1.6 (D6): UN solo Actuador + el agente como Crítico.

---

## Fases

### F1 — ampliar_contexto con estructura cronológica pasa por RecoveryCycle (criterio 1)

- **Archivos:** `pipeline.py` (función `ampliar_contexto`)
- **Cambio:**
  - Cuando `ampliar_contexto()` detecta `estructura = "cronologico"`, en vez de ir directo a `ProcesadorDocumento`, debe:
    1. Construir intercambios desde el contenido (como RecoveryCycle hace con mensajes del chat).
    2. Pasar los intercambios por `RecoveryCycle` (que clasifica, empaqueta con BlockPacker, y genera bloques físicos + archivos de recuperación).
  - Si `estructura = "arbitrario"`: sigue el flujo actual (ProcesadorDocumento).
  - Reusar RecoveryCycle, no duplicar lógica.
- **Estado:** ❌ Pendiente

### F2 — BlockPacker ordena bloques externos cronológicos descendentes (criterio 2)

- **Archivos:** `pipeline.py`, `processing/block_packer.py`
- **Cambio:**
  - Verificar que BlockPacker recibe los intercambios con timestamps correctos.
  - BlockPacker ya ordena descendente (línea 142: `all_exchanges.sort(key=lambda ex: ex.start_timestamp, reverse=True)`).
  - Asegurar que los intercambios construidos desde el archivo externo tengan `start_timestamp` poblado correctamente.
  - Si ampliar_contexto pasa por RecoveryCycle (F1), BlockPacker se usa automáticamente.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1

### F3 — P2 no se realiza si contexto_recuperacion no existe (criterio 3)

- **Archivos:** `pipeline.py`, `mini-services/pipeline-daemon/index.py`
- **Cambio:**
  - Si `contexto_recuperacion/` no existe, el daemon no llama `_auditar_y_completar()` ni `AuditorWorkspace.auditar_completitud()`.
  - El proceso va directo a procesar la fuente.
  - Si `contexto_recuperacion/` existe, P2 se realiza normalmente (auditar + completar lo faltante).
- **Estado:** ❌ Pendiente

### F4 — P16 siempre se realiza tras procesar (criterio 4)

- **Archivos:** `pipeline.py`
- **Cambio:**
  - Tras el enriquecimiento (P14), P16 (auditoría final con `AuditorWorkspace.auditar_completitud()`) SIEMPRE se ejecuta.
  - Verificar que P16 está después de P14 y antes de P17 en `ContextoPipeline.run()`.
  - Si el proceso va por ampliar_contexto → RecoveryCycle → collect_responses → cascada, P16 se ejecuta al final de la cascada.
- **Estado:** ❌ Pendiente

### F5 — Orquestación del flujo completo en el daemon (criterio 5)

- **Archivos:** `mini-services/pipeline-daemon/index.py`, `pipeline.py`
- **Cambio:**
  - El daemon implementa el endpoint `ampliar-contexto` (hoy devuelve 501).
  - El flujo del daemon cuando se invoca ampliar-contexto:
    - Si `estructura = "cronologica"`:
      1. `ampliar_contexto()` → RecoveryCycle (construye intercambios, clasifica, BlockPacker ordena descendente, genera bloques).
      2. Si hay pending_tasks de extracción, devolver el control al agente CZAI.
      3. Cuando el agente CZAI termine los subagentes, llamar `collect_responses()`.
      4. Tras integrar, verificar bloques incompletos con `_descubrir_bloques_incompletos()`.
      5. Si hay incompletos, disparar cascada.
      6. P16 + P17 + P18 + P19.
    - Si `estructura = "arbitrario"`:
      1. `ampliar_contexto()` → ProcesadorDocumento (divide en lotes, publica pending_tasks).
      2. Devolver el control al agente CZAI con las pending_tasks.
      3. Cuando el agente CZAI termine los subagentes, llamar `collect_responses()`.
      4. Tras integrar, verificar bloques incompletos.
      5. Si hay incompletos, disparar cascada.
      6. P16 + P17 + P18 + P19.
  - Si `contexto_recuperacion/` ya existe, el daemon solo audita y completa (F3 de v6.17).
- **Estado:** ❌ Pendiente
- **Dependencias:** F1, F3, F4

### F6 — Reconstruir contexto desde exchanges_czai_consolidados.md

- **Qué se hace:**
  1. Borrar workspace `contexto_recuperacion/`.
  2. Invocar al daemon con la fuente.
  3. El daemon ejecuta el flujo orquestado F1-F5.
  4. F1: estructura cronológica → RecoveryCycle → BlockPacker ordena descendente.
  5. F5: subagentes extraen → collect_responses integra → cascada enriquece.
  6. F4: P16 auditoría final.
- **Estado:** ❌ Pendiente
- **Dependencias:** F1-F5

### F7 — Gauntlet de terminación

- **Qué se hace:**
  1. Ejecutar los 7 pasos del Gauntlet.
  2. Verificar los 5 criterios de aceptación.
  3. Si no pasa → bucle D7.
  4. Si pasa → empaquetado.
- **Estado:** ❌ Pendiente
- **Dependencias:** F6

---

## Orden de ejecución

| Fase | Descripción | Deps |
|---|---|---|
| F1 | ampliar_contexto cronológico pasa por RecoveryCycle | ninguna |
| F2 | BlockPacker ordena bloques externos descendentes | F1 |
| F3 | P2 no se realiza si contexto no existe | ninguna |
| F4 | P16 siempre se realiza tras procesar | ninguna |
| F5 | Orquestación del flujo completo en el daemon | F1, F3, F4 |
| F6 | Reconstruir contexto | F1-F5 |
| F7 | Gauntlet de terminación | F6 |

---

**Fin del plan v6.18.**
