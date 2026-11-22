# contexto_zai/Documentos/plan_refactorizacion_v6.11.md
# Plan v6.11 — Separación de capas + paginación + MessageExtractor + OOP + 4 archivos por tipo de fuente

**Versión:** 6.11
**Fecha:** 2026-10-30
**Estado:** Implementado (commit `554b135`).
**Continuación de:** plan v6.10.
**Spec asociada:** spec_recuperacion_contexto_v6.11.md

---

## Objetivo

Implementar los 4 cambios especificados en la spec v6.11:
1. Adaptar `get_message_tree()` al nuevo endpoint (resolver HTTP 405 del Paso 5).
2. Separar capas: `MessageExtractor` en `processing/`, eliminar fugas de `client/` en `process/`.
3. Paginación del batch en lotes de `BATCH_SIZE=100`.
4. Refactorización OOP de `pipeline.py` + 4 archivos por tipo de fuente.

---

## No olvidar del DTI

- NH1: diagnóstico y consenso previo — hecho (informe del EP del 2026-10-26).
- NH8: autorización del Director — concedida (orden del 2026-10-30).
- NH14: decisión de arquitectura consensuada — la separación de capas y el MessageExtractor son decisiones consensuadas.
- NH18: cambios quirúrgicos, no reescribir.
- NH19: validar antes de entregar.
- NH23: solo tocar lo pedido.
- NH25: baremo de datos reales — validar contra el chat EP (e2560b1e) con 89 exchanges.

---

## Principio: separación de capas + no fuga

`process/` NO importa de `client/`. Si necesita extraer mensajes, lo hace a través de `MessageExtractor` (que vive en `processing/`). Lo que ya funciona NO se toca.

---

## Fases

### F1 — Adaptar `get_message_tree()` al nuevo endpoint

**Archivos:** `client/chat_client.py`.

**Qué se hace:**
1. Reemplazar `GET /api/v1/chats/share/{share_id}` por `POST /api/v1/chats/{chat_id}/messages/list` con `{"content": "all"}`.
2. Adaptar el parseo de la respuesta nueva (`chat.history.messages` como dict con `id`, `parentId`, `childrenIds`, `role`, `timestamp`).
3. Devolver lista plana de mensajes con sus IDs.

**Lo que NO se toca:**
- El endpoint `POST /api/v1/chats/{chat_id}/messages/batch`.
- La lógica de creación de share (si ya existe, se reutiliza).
- `AuthClient`.

### F2 — Separar capas: `MessageExtractor` en `processing/`

**Archivos:** `processing/message_extractor.py` (nuevo), `process/recovery_cycle.py`, `process/incremental_cycle.py`, `process/orchestrator.py`.

**Qué se hace:**
1. Crear `processing/message_extractor.py` con la clase `MessageExtractor(jwt, chat_id)`.
2. Métodos: `get_new_messages(since_timestamp)` (filtra ANTES de descargar) y `get_all_messages()`.
3. `RecoveryCycle` y `IncrementalCycle` usan `MessageExtractor`, no `ChatClient` directo.
4. Eliminar imports de `client/` en `process/`.

**Lo que NO se toca:**
- `ChatClient` (sigue en `client/`).
- `AuthClient`.
- Los prompts.

### F3 — Paginación del batch

**Archivos:** `client/chat_client.py`, `config.py`.

**Qué se hace:**
1. `ChatClient.get_messages_batch()` divide `message_ids` en lotes de `BATCH_SIZE=100`.
2. Cada lote: petición separada `POST /api/v1/chats/{chat_id}/messages/batch` con `{"ids": [...]}`.
3. Resultados acumulados en una sola lista.
4. Reintento con backoff (2s, 4s, 8s) si un lote falla.

**Lo que NO se toca:**
- El formato del body del batch.
- Los headers de autenticación.

### F4 — Refactorización OOP + 4 archivos por tipo de fuente

**Archivos:** `pipeline.py`, `config.py`, `client/zai_config.py` (nuevo), `procesadores/`, `coordinador/integrador_respuestas.py`.

**Qué se hace:**
1. `pipeline.py` refactorizado a OOP: clase `ContextoPipeline` con métodos estáticos (`run`, `ampliar_contexto`, `collect_responses`, `query_context`). Las funciones módulo-nivel son wrappers momentáneos.
2. `config.py` con `APIConfig` dataclass para centralizar URLs.
3. `client/zai_config.py` (nuevo): configuración específica de la API de Z.ai.
4. 4 archivos por tipo de fuente: `procesador_intercambios.py`, `procesador_documento.py`, `procesador_consulta.py`, `integrador_respuestas.py`.

**Lo que NO se toca:**
- Los generadores (`generation/`).
- Los modelos Pydantic (`models.py`).

### F5 — Tests

**Archivos:** `tests/test_v42_e2e.py`, `tests/test_recovery_cycle.py`, `tests/test_e2e_pipeline.py`.

**Qué se hace:**
1. Actualizar tests para reflejar la nueva estructura (MessageExtractor, ContextoPipeline).
2. Verificar que los mocks usan `MessageExtractor`, no `ChatClient` directo.
3. Tests E2E: 30/30 deben pasar.

### F6 — Validación con datos reales

**Qué se hace:**
1. Ejecutar `RecoveryCycle` sobre un chat real (sin HTTP 405).
2. Ejecutar `IncrementalCycle` sobre un chat con metadata previa (extrae solo mensajes nuevos).
3. Sobre un chat de más de 200 mensajes, verificar que el batch pagina sin timeout.
4. Verificar imports: `from pipeline import ContextoPipeline` funciona.

### F7 — Gauntlet + entrega

**Qué se hace:**
1. Gauntlet determinista: regresión + perímetro + estática + dinámica + lógica.
2. Veredicto JSON: aprobado, sin items_fallados.
3. `.zip` en `/download/` con archivos modificados + `1-LEER-PRIMERO.txt`.
4. Sentencias de validación para Windows en el chat.

---

## Orden de ejecución

| Fase | Dependencias | Estado |
|---|---|---|
| F1 — Adaptar get_message_tree | ninguna | Implementado |
| F2 — MessageExtractor + separar capas | F1 | Implementado |
| F3 — Paginación del batch | F1 | Implementado |
| F4 — Refactor OOP + 4 archivos | F2 | Implementado |
| F5 — Tests | F1, F2, F3, F4 | Implementado (30/30) |
| F6 — Validación con datos reales | F5 | Implementado (89 exchanges extraídos) |
| F7 — Gauntlet + entrega | F6 | Implementado (commit 554b135) |

**Total estimado:** 1 sesión.

---

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El nuevo endpoint `messages/list` cambia de estructura | Media | Alto | Test contra chat real antes de entregar |
| `MessageExtractor` no filtra correctamente por timestamp | Media | Alto | Test con `since_timestamp` conocido |
| La paginación pierde mensajes en los límites de lote | Baja | Alto | Verificar que la suma de lotes = total de IDs |
| El refactor OOP rompe imports existentes | Media | Medio | Wrappers momentáneos que delegan a la clase |

---

## Entrega

- Archivos modificados en `.zip` con estructura `para-repo-contexto_zai/` + `1-LEER-PRIMERO.txt`.
- Instrucciones de validación en Windows por el chat.
- Commit sugerido: `v6.11: separacion de capas + paginacion + MessageExtractor + OOP + 4 archivos por tipo de fuente`.

---

## Resultado real (2026-10-30)

- Commit `554b135` aplicado.
- Run sobre chat EP: 89 exchanges extraídos sin HTTP 405.
- 77 bloques generados.
- Worker Bun no procesó (problema detectado → alimenta spec v6.12).
- Falso positivo de contabilidad detectado (76/76 resueltas con 75 pendientes → alimenta spec v6.12).

---

**Fin del plan v6.11.**
