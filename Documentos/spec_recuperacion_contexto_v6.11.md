# contexto_zai/Documentos/spec_recuperacion_contexto_v6.11.md
# Spec v6.11 — Separación de capas + paginación + MessageExtractor + OOP + 4 archivos por tipo de fuente

**Versión:** 6.11
**Fecha:** 2026-10-30
**Estado:** Implementada (commit `554b135`).
**Especifica continuación de:** spec v6.10.

---

## 1. Propósito

La v6.10 dejó tres problemas detectados tras el run del 2026-10-26 sobre el chat EP (informe `informe_agente_CZAI_fallo_paso5_405.md`):

1. **Paso 5 (extracción) falla con HTTP 405** al leer `GET /api/v1/chats/share/{share_id}`. La plataforma cambió la forma de llamada del endpoint del árbol de mensajes.
2. **Los módulos del proceso tienen fugas de capas** (`from contexto_zai.client import ...` en `process/recovery_cycle.py`, `process/incremental_cycle.py`, `process/orchestrator.py`) que violan el principio de separación de capas y acoplan el proceso a la plataforma.
3. **Sin paginación en el batch de mensajes** — el endpoint `POST /api/v1/chats/{chat_id}/messages/batch` recibe todos los `message_ids` de una sola vez, lo que excede el timeout en chats grandes.

Esta spec resuelve los tres problemas con una refactorización OOP que separa capas, introduce `MessageExtractor` para filtrar por timestamp antes de descargar, y pagina el batch en lotes de `BATCH_SIZE=100`.

---

## 2. Principio rector: separación de capas + no fuga

**Capas del proceso (de afuera hacia adentro):**

1. **Capa de plataforma** (`client/`): conoce la API de Z.ai (JWT, share, batch).
2. **Capa de proceso** (`process/`): orquesta recuperación e incremental, NO conoce la plataforma directamente.
3. **Capa de procesamiento** (`processing/`): construye exchanges, clasifica, empaqueta bloques.
4. **Capa de generación** (`generation/`): produce los archivos de recuperación.

**Regla de no fuga:** `process/` NO importa de `client/`. Si necesita extraer mensajes, lo hace a través de `MessageExtractor` (que vive en `processing/`), no de `ChatClient` directamente.

**Lo que ya funciona NO se toca:**
- Bloques con contenido literal hasta 70K ✅
- RESUMEN al inicio de cada bloque ✅
- Worker Bun como camino prioritario de enriquecimiento ✅
- Arnés Worker Bun/subagentes de v6.10 ✅
- Carga automática del JWT ✅

---

## 3. Los tres problemas a resolver

### Problema 1 — HTTP 405 en el Paso 5 (extracción)

**Qué pasa hoy:** `GET /api/v1/chats/share/{share_id}` devuelve HTTP 405 Method Not Allowed. La plataforma cambió la forma de llamada del endpoint del árbol de mensajes.

**Impacto:** el `RecoveryCycle` no puede extraer mensajes. Todo el proceso se detiene en el Paso 5.

**Causa raíz:** el endpoint por `share_id` como invitado dejó de funcionar (documentado en `chat_client.py` cabecera v3.2, líneas 7-9). El batch v3.2 ya usa `chat_id` autenticado, pero el árbol sigue llamando al endpoint viejo.

### Problema 2 — Fugas de capas en `process/`

**Qué pasa hoy:** `process/recovery_cycle.py`, `process/incremental_cycle.py` y `process/orchestrator.py` importan directamente de `contexto_zai.client` (ej: `from contexto_zai.client import ChatClient`). Eso acopla el proceso a la plataforma.

**Impacto:** cualquier cambio en `client/` rompe `process/`. No se puede测试ear el proceso sin mockear la API completa.

**Causa raíz:** el `RecoveryCycle` y el `IncrementalCycle` llaman a `ChatClient.extract_all_with_raw()` directamente, sin un intermediario que abstraiga la extracción.

### Problema 3 — Sin paginación en el batch

**Qué pasa hoy:** `ChatClient.get_messages_batch()` envía todos los `message_ids` (pueden ser cientos) en una sola petición `POST /api/v1/chats/{chat_id}/messages/batch`. En chats grandes, eso excede el timeout del servidor.

**Impacto:** el proceso muere con timeout o HTTP 422 (body demasiado grande) en chats de más de ~300 mensajes.

**Causa raíz:** no hay paginación en el batch. El endpoint acepta lotes de hasta 100 IDs, pero el cliente no los divide.

---

## 4. Soluciones

### F1 — Adaptar `get_message_tree()` al nuevo endpoint (Problema 1)

**Qué se hace:**
1. Reemplazar `GET /api/v1/chats/share/{share_id}` por `POST /api/v1/chats/{chat_id}/messages/list` con `{"content": "all"}` (endpoint autenticado por `chat_id`, no `share_id` invitado).
2. El árbol devuelto tiene estructura nueva: `chat.history.messages` es un dict (no una lista), con `id`, `parentId`, `childrenIds`, `role`, `timestamp`.
3. `ChatClient.get_message_tree()` se adapta al nuevo formato y devuelve la lista plana de mensajes con sus IDs.

**Lo que NO se toca:**
- El endpoint `POST /api/v1/chats/{chat_id}/messages/batch` (sigue funcionando).
- La lógica de creación de share (si el share ya existe, se reutiliza).
- El `AuthClient` (no se modifica).

### F2 — Separar capas: `MessageExtractor` en `processing/` (Problema 2)

**Qué se hace:**
1. Crear `processing/message_extractor.py` con la clase `MessageExtractor`.
2. `MessageExtractor` es el intermediario entre `client/ChatClient` y `process/RecoveryCycle`:
   - Recibe `jwt` y `chat_id` en el constructor.
   - `get_new_messages(since_timestamp)`: devuelve solo los mensajes posteriores al timestamp (filtra ANTES de descargar el contenido, resolviendo el timeout en chats grandes).
   - `get_all_messages()`: devuelve todos los mensajes del chat.
3. `RecoveryCycle` y `IncrementalCycle` ya no importan de `client/`. Usan `MessageExtractor`.
4. `process/orchestrator.py` ya no importa de `client/`.

**Lo que NO se toca:**
- `ChatClient` (sigue existiendo en `client/`, pero `process/` no lo importa directamente).
- `AuthClient` (no se modifica).
- Los prompts de enriquecimiento.
- Los archivos de comunicación (`_pending_blocks.json`, `_responses/`).

### F3 — Paginación del batch (Problema 3)

**Qué se hace:**
1. `ChatClient.get_messages_batch()` divide los `message_ids` en lotes de `BATCH_SIZE=100` (constante en `config.py`).
2. Cada lote se envía como una petición separada `POST /api/v1/chats/{chat_id}/messages/batch` con `{"ids": [...]}`.
3. Los resultados se acumulan en una sola lista.
4. Si un lote falla, se reintenta con backoff exponencial (2s, 4s, 8s).

**Lo que NO se toca:**
- El formato del body del batch (`{"ids": [...]}`).
- Los headers de autenticación.
- El manejo de rate limit (429) existente.

### F4 — Refactorización OOP + 4 archivos por tipo de fuente

**Qué se hace:**
1. `pipeline.py` refactorizado a OOP: clase `ContextoPipeline` con métodos estáticos (`run`, `ampliar_contexto`, `collect_responses`, `query_context`). Las funciones módulo-nivel son wrappers momentáneos que delegan.
2. `config.py` con `APIConfig` dataclass para centralizar URLs y constantes.
3. `client/zai_config.py` (nuevo): configuración específica de la API de Z.ai (`base_url`, `messages_batch_by_chat_url`, etc.).
4. 4 archivos por tipo de fuente: `procesadores/procesador_intercambios.py` (chat actual), `procesadores/procesador_documento.py` (PDFs/docs), `procesadores/procesador_consulta.py` (links /s/), `coordinador/integrador_respuestas.py` (consolida respuestas de subagentes).

**Lo que NO se toca:**
- Los generadores (`generation/`).
- Los modelos Pydantic (`models.py`).
- Los tests E2E existentes (se actualizan para reflejar la nueva estructura).

---

## 5. Archivos intervenidos

| Archivo | Cambio |
|---|---|
| `client/chat_client.py` | F1: adaptar `get_message_tree()` al nuevo endpoint. F3: paginación del batch. |
| `client/zai_config.py` (nuevo) | F4: configuración de la API de Z.ai. |
| `processing/message_extractor.py` (nuevo) | F2: `MessageExtractor` que filtra por timestamp antes de descargar. |
| `processing/exchange_builder.py` | F4: ajustes para el nuevo formato de mensajes. |
| `process/recovery_cycle.py` | F2: usar `MessageExtractor` en vez de `ChatClient` directo. |
| `process/incremental_cycle.py` | F2: usar `MessageExtractor`. |
| `process/orchestrator.py` | F2: sin imports de `client/`. |
| `pipeline.py` | F4: refactor OOP, clase `ContextoPipeline`. |
| `config.py` | F3: `BATCH_SIZE=100`. F4: `APIConfig` dataclass. |
| `coordinador/integrador_respuestas.py` | F4: consolidar respuestas de subagentes. |
| `subagents/mantenimiento_subagent.py` | F4: ajustes para la nueva estructura. |
| `tests/test_v42_e2e.py` | Actualizar tests para reflejar la nueva estructura. |
| `tests/test_recovery_cycle.py` | Actualizar tests. |

---

## 6. Lo que NO se toca

- Worker Bun (código TypeScript, prompts, backoff).
- `CredentialManager` (no se modifica).
- Bookmarklet ni el flujo de conexión del Director.
- Bloques físicos (nombre, contenido, RESUMEN).
- Especificaciones y planes de versiones anteriores (ya en el historial).
- La estructura de archivos de recuperación (`00_estado_actual.md`, `01_indice_recuperacion.md`, etc.).
- El arnés Worker Bun/subagentes de v6.10 (sigue funcionando).

---

## 7. Criterios de aceptación

1. `python config.py` pasa todos sus auto-tests.
2. `from client.zai_config import API_CONFIG` funciona y `API_CONFIG.base_url` devuelve `https://chat.z.ai`.
3. `ChatClient.get_messages_batch()` tiene el parámetro `batch_size` y pagina en lotes de 100.
4. `MessageExtractor` tiene el método `get_new_messages(since_timestamp)`.
5. `process/recovery_cycle.py` no contiene `from contexto_zai.client` (sin fugas).
6. `process/incremental_cycle.py` no contiene `from contexto_zai.client` (sin fugas).
7. `process/orchestrator.py` no contiene `from contexto_zai.client` (sin fugas).
8. `from pipeline import ProgressMonitor` funciona (pre-existe de v6.10, no se rompe).
9. `from pipeline import EnriquecimientoOrquestador` funciona.
10. Tests E2E: 30/30 pasan.

---

## 8. Validación con datos reales

1. **Test F1 (nuevo endpoint):** ejecutar `RecoveryCycle` sobre un chat real. Debe extraer mensajes sin HTTP 405.
2. **Test F2 (MessageExtractor):** ejecutar `IncrementalCycle` sobre un chat con metadata previa. Debe extraer solo mensajes nuevos (posteriores al `ultimo_timestamp`).
3. **Test F3 (paginación):** sobre un chat de más de 200 mensajes, verificar que el batch se divide en lotes de 100 y no excede el timeout.
4. **Test F4 (OOP):** `from pipeline import ContextoPipeline` y verificar que `ContextoPipeline.run()`, `ampliar_contexto()`, `collect_responses()`, `query_context()` existen.

---

## 9. Hallazgos del run real (2026-10-30, chat EP)

El run de v6.11 sobre el chat EP (informe `informe_agente_CZAI_run_v6.11_worker_bun_proxy_apa.md`) confirmó:

1. **Paso 5 resuelto:** 89 exchanges extraídos sin HTTP 405. La paginación del batch funcionó.
2. **Worker Bun no procesó bloques** (arranque manual apuntando al workspace equivocado + ventana de 5s insuficiente para 76 bloques).
3. **Falso positivo de contabilidad:** el run cerró con "76 de 76 resueltas" cuando 75 bloques seguían sin RESUMEN. La contabilidad se basaba en la cola `_pending_tasks.json` (que no existía en el workspace de ejecución), no en el estado físico de los bloques.

Estos hallazgos alimentan la spec v6.12.

---

**Fin de la spec v6.11.**
