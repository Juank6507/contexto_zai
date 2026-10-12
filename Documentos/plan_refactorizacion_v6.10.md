# contexto_zai/Documentos/plan_refactorizacion_v6.10.md
# Plan v6.10 — Carga automática del JWT + eliminación de errores silenciados + arnés Worker Bun/subagentes

**Versión:** 6.10
**Fecha:** 2026-10-12
**Estado:** Pendiente de implementación.
**Continuación de:** plan v6.9.
**Spec asociada:** spec_recuperacion_contexto_v6.10.md

---

## Objetivo

Implementar los 4 cambios especificados en la spec v6.10:
1. Carga automática del JWT.
2. Eliminación de los dos `try/except` silenciosos.
3. Arnés Worker Bun / subagentes.
4. Re-aplicación de fixes v6.8.1, v6.8.3, v6.8.4 perdidos.

---

## No olvidar del DTI

- NH1: diagnóstico y consenso previo — hecho (Fases D y C con el Director).
- NH8: autorización del Director — pendiente (este plan espera aprobación).
- NH14: decisión de arquitectura consensuada — el arnés es decisión consensuada.
- NH18: cambios quirúrgicos, no reescribir.
- NH19: validar antes de entregar.
- NH23: solo tocar lo pedido.

---

## Principio: proteger lo existente

Lo que ya funciona NO se toca. Los cambios son quirúrgicos en tres puntos del proceso.

---

## Fases

### F1 — Carga automática del JWT

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En el proceso principal, si el parámetro `jwt` llega vacío, cargarlo del `CredentialManager`.
2. Si después de cargarlo sigue vacío, devolver un error claro: "No hay JWT disponible. Pedí al Director que reconecte CZAI desde el sandbox."
3. El parámetro `jwt` pasa a tener valor por defecto vacío (ya no es obligatorio).

**Lo que NO se toca:**
- `CredentialManager` (no se modifica).
- Bookmarklet ni el flujo de conexión del Director.
- El resto del proceso principal.

### F2 — Eliminar los dos `try/except` silenciosos

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. En `_enriquecer_bloques_post_run` (la función que enriquece bloques después de la activación principal), eliminar el `try/except Exception` que envuelve todo el bloque.
2. En `collect_responses` (la función que recoge respuestas de subagentes), eliminar el `try/except` similar y capturar el valor de retorno del enriquecimiento directamente, sin re-leer del Orquestador.
3. Re-aplicar el fix de v6.8.1: el enriquecimiento devuelve las pending_tasks en su valor de retorno. El agente las recibe directamente.

**Lo que NO se toca:**
- La lógica interna del enriquecimiento (sigue siendo la misma).
- El Worker Bun.
- Los prompts.

### F3 — Arnés Worker Bun / subagentes

**Archivos:** `pipeline.py`.

**Qué se hace:**
1. Modificar `_enriquecer_bloques_con_fallback` para que sea no bloqueante:
   - Detectar la caída del Worker Bun sin esperar al timeout completo.
   - Cuando cae: devolver la tarea en proceso a la lista de pendientes y construir las pending_tasks para el agente inmediatamente.
   - Lanzar el Worker Bun en segundo plano (proceso no bloqueante) mientras los subagentes trabajan, para detectar cuándo se recupera.
2. Cuando el Worker Bun se recupera: dejar que el lote actual de subagentes termine, luego volver al Worker Bun como camino prioritario.
3. Re-aplicar el fix de v6.8.3: verificar que el Worker Bun realmente procesó bloques tras esperar (no asumir éxito).

**Lo que NO se toca:**
- El Worker Bun en sí (código TypeScript, backoff, prompts).
- La idempotencia (Worker Bun y subagentes verifican RESUMEN antes de procesar).
- Los archivos de comunicación entre Python y Worker Bun (`_pending_blocks.json`, `_responses/`).

### F4 — Re-aplicación de fixes perdidos

**Archivos:** `pipeline.py`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. Re-aplicar v6.8.1 (parte de F2).
2. Re-aplicar v6.8.3 (parte de F3).
3. Re-aplicar v6.8.4:
   - `_integrar_documento` no registra temas provisionales en `tema_a_archivo`.
   - Definir `_regenerar_indice_tras_enriquecimiento` y `_normalizar_bloques_externos`.
   - `collect_responses` invoca `_regenerar_indice_tras_enriquecimiento` tras el enriquecimiento.

**Lo que NO se toca:**
- Las specs y planes de v6.8.1, v6.8.3, v6.8.4 (ya existen en el historial).
- El comportamiento documentado en esas specs (se respetan íntegramente).

### F5 — Tests

**Archivos:** `tests/test_v42_e2e.py`, `coordinador/integrador_respuestas.py` (tests atómicos en `__main__`).

**Qué se hace:**
1. Actualizar tests que asumían el `try/except` silencioso.
2. Actualizar tests que asumían temas provisionales en `tema_a_archivo`.
3. Añadir test que verifique la carga automática del JWT.
4. Añadir test que verifique que el arnés entrega pending_tasks en menos de 5 segundos cuando el Worker Bun cae.

**Lo que NO se toca:**
- Tests que no se ven afectados por los cambios.

### F6 — Validación con datos reales

**Qué se hace:**
1. Ejecutar el proceso principal sin pasar JWT (vacío) y verificar que lo carga automáticamente.
2. Simular una falla en el enriquecimiento y verificar que las `pending_tasks` llegan al agente.
3. Con el servicio de Z.ai saturado (429), verificar que el agente recibe las `pending_tasks` en menos de 5 segundos.
4. Verificar que las funciones críticas se importan sin error.

---

## Orden de ejecución

| Fase | Dependencias | Estado |
|---|---|---|
| F4 — Re-aplicar fixes perdidos | ninguna | Pendiente |
| F1 — Carga automática del JWT | ninguna | Pendiente |
| F2 — Eliminar try/except silenciosos | F4 | Pendiente |
| F3 — Arnés Worker Bun/subagentes | F2 | Pendiente |
| F5 — Tests | F1, F2, F3, F4 | Pendiente |
| F6 — Validación con datos reales | F5 | Pendiente |

**Total estimado:** 1 sesión.

---

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El arnés no detecta correctamente la caída del Worker Bun | Media | Alto | Test con 429 simulado + verificación de pending_tasks en menos de 5s |
| El Worker Bun se recupera pero el arnés no lo detecta | Baja | Medio | Monitor en segundo plano con health check periódico |
| Los subagentes no terminan su lote cuando el Worker Bun se recupera | Baja | Bajo | El lote se deja terminar siempre (no se interrumpe) |
| La carga automática del JWT rompe tests existentes | Baja | Bajo | Tests actualizados en F5 |

---

## Entrega

- Archivos modificados en `.zip` con estructura `para-repo-contexto_zai/` + `1-LEER-PRIMERO.txt`.
- Instrucciones de validación en Windows por el chat (no en el `.zip`).
- Commit sugerido para el Director.

---

**Fin del plan v6.10.**
