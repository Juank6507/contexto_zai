# contexto_zai/Documentos/plan_refactorizacion_v6.9.md
# Plan v6.9 — Eliminar camino duplicado: link /s/ pasa por el mismo flujo que archivos externos

**Versión:** 6.9
**Fecha:** 2026-10-08
**Estado:** Pendiente.
**Continuación de:** plan v6.8.4.
**Spec asociada:** spec_recuperacion_contexto_v6.9.md

## Objetivo

Eliminar el camino duplicado del link `/s/` que delega a `pipeline.run()` y
sobrescribe bloques existentes. El link `/s/` pasa por el mismo camino que
un archivo externo, preservando los bloques existentes.

## No olvidar del DTI

- NH1: diagnóstico y consenso previo — hecho.
- NH8: autorización del Director — concedida.
- NH14: decisión de arquitectura consensuada — eliminar camino duplicado.
- NH18: cambios quirúrgicos, no reescribir.
- NH19: validar antes de entregar.
- NH23: solo tocar lo pedido.

## Principio: proteger lo existente

Lo que ya funciona NO se toca. Los cambios son quirúrgicos en
`ampliar_contexto()`.

## Fases

### F1 — Eliminar la delegación del link /s/ a pipeline.run()

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Eliminar el bloque de código en `ampliar_contexto()` que detecta `/s/`
   y delega a `pipeline.run()`.
2. Eliminar también el bloque que detecta `/c/` y delega a `pipeline.run()`.
3. Tanto `/s/` como `/c/` pasan por el flujo de archivos externos
   (ProcesadorDocumento → subagentes → _integrar_documento).

**Lo que NO se toca:**
- `pipeline.run()` sigue funcionando para recuperación de chat.
- `RecoveryCycle` sigue funcionando.
- `BlockPacker` sigue funcionando.

### F2 — Extraer contenido del chat /s/ como fuente externa

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Cuando `ampliar_contexto()` recibe un link `/s/` o `/c/` de Z.ai:
   - Extraer el `share_id` o `chat_id` de la URL.
   - Usar `ChatClient.extract_all()` para obtener los mensajes del chat.
   - Guardar el contenido como un archivo temporal (igual que los APA).
   - Pasar ese archivo al `ProcesadorDocumento` que lo procesa como
     una fuente externa.
2. El contenido del chat se escribe como bloques nuevos sin sobrescribir
   los existentes (gracias a `_siguiente_nombre_bloque()`).
3. Los bloques nuevos se enriquecen igual que los externos.

**Lo que NO se toca:**
- `ProcesadorDocumento` — no se modifica.
- `IntegradorRespuestas._integrar_documento()` — no se modifica.
- `_siguiente_nombre_bloque()` — no se modifica.

### F3 — Actualizar el metadata correctamente

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `archivo_a_source` se actualiza con el origen del link
   (source_type="url", source_path=<url>, share_id=<share_id>).
2. `ultimo_timestamp` se actualiza si los intercambios son posteriores.
3. La generación de los 4 archivos depende de la cronología
   (Principio 3 de v6.7).

### F4 — Tests con datos reales

**Archivos:** `tests/test_v42_e2e.py`, `__main__` de `pipeline.py`.

**Qué se hace:**
1. Test: workspace con 3 bloques → ampliar con link `/s/` (mockeado)
   → los 3 bloques se preservan → los nuevos se numeran desde bloque_04.
2. Test: ampliar con link `/s/` → `archivo_a_source` registra el origen.
3. Test: ampliar con link `/c/` → mismo comportamiento.
4. Test de regresión: ampliar con archivo externo sigue funcionando igual.
5. Test de regresión: `pipeline.run()` (recuperación directa) sigue
   funcionando igual.

### F5 — Validación end-to-end

**Qué se hace:**
1. Ejecutar todos los `__main__` atómicos.
2. Ejecutar los 30+ tests E2E.
3. Validar con datos reales que:
   - Los bloques existentes se preservan al ampliar con link `/s/`.
   - Los bloques nuevos se numeran desde el último existente.
   - El metadata es consistente (archivo_a_source correcto).
   - El enriquecimiento funciona (RESUMEN + temas).
   - El índice se regenera correctamente.

---

**Fin del plan v6.9.**
