# contexto_zai/Documentación/plan_refactorizacion_v5.0.md
# Plan v5.0 — Proxy de subagentes + Separación de plataforma

**Versión:** 5.0
**Fecha:** 2026-09-20
**Autor:** Agente CZAI (Sesión 19, con consenso del Director)
**Estado:** Pendiente de validación por el Director.
**Continúa de:** plan v4.5 (índice multi-bloque + 03 ampliado + eliminación de 04_resumenes).
**Spec asociada:** spec_recuperacion_contexto_v5.0.md.

---

## Estructura del plan

El plan se organiza en 4 fases (F1–F4):

1. Crear las interfaces de plataforma y las implementaciones de Z.ai.
2. Crear el proxy de subagentes (servicio que llama al LLM directamente).
3. Conectar el proceso al proxy (opt-in: si el proxy está, lo usa; si no, sigue como hoy).
4. Tests E2E y verificación final (incluyendo medición de latencia).

**Total de archivos nuevos:** ~8 (interfaces + implementaciones Z.ai + proxy).
**Total de archivos intervenidos:** ~4 (orchestrator, pipeline, recovery_cycle, config).
**Tests nuevos:** 6 atómicos + 2 E2E.

---

## F1 — Interfaces de plataforma + implementaciones de Z.ai

**Prioridad:** ALTA — es la base de la portabilidad.
**Dependencias:** ninguna.
**Estimación:** 1.5 sesiones.

### Qué se hace

1. **Crear `contexto_zai/platform/__init__.py`** — paquete que exporta las interfaces.

2. **Crear `contexto_zai/platform/interfaces.py`** — 4 interfaces abstractas:
   - `PlatformAuth`: `get_token()`, `create_share(chat_id)`.
   - `PlatformChat`: `extract_messages(chat_id, share_id)`, `get_chat_tree(share_id)`.
   - `PlatformLinks`: `parse_link(url)`, `is_platform_link(url)`.
   - `PlatformLLM`: `complete(prompt, system_prompt)`, `complete_batch(prompts)`.

3. **Crear `contexto_zai/platform/zai/__init__.py`** — paquete de implementaciones de Z.ai.

4. **Crear `contexto_zai/platform/zai/zai_auth.py`** — `ZaiAuth(PlatformAuth)`:
   - Envuelve `AuthClient` existente.
   - `get_token()` devuelve el JWT.
   - `create_share(chat_id)` llama a `AuthClient.create_share()`.

5. **Crear `contexto_zai/platform/zai/zai_chat.py`** — `ZaiChat(PlatformChat)`:
   - Envuelve `ChatClient` existente.
   - `extract_messages()` llama a `ChatClient.extract_all()`.
   - `get_chat_tree()` llama a `ChatClient.get_message_tree()`.

6. **Crear `contexto_zai/platform/zai/zai_links.py`** — `ZaiLinks(PlatformLinks)`:
   - `parse_link(url)` usa `_extraer_id_de_link()` existente.
   - `is_platform_link(url)` verifica si es `chat.z.ai/s/` o `/c/`.

7. **Crear `contexto_zai/platform/zai/zai_llm.py`** — `ZaiLLM(PlatformLLM)`:
   - `complete(prompt)` llama a `internal-api.z.ai/v1/chat/completions` con las credenciales del sandbox.
   - `complete_batch(prompts)` lanza varias peticiones en paralelo.
   - Reutiliza el patrón del proxy de APA (`_lib.ts` lee `/etc/.z-ai-config`).
   - **Pero en Python**, no TypeScript — usa `httpx` para las peticiones HTTP.

8. **Intervenir `contexto_zai/process/orchestrator.py`** — aceptar las interfaces:
   - `__init__()` acepta `auth`, `chat`, `links`, `llm` opcionales.
   - Si no se pasan, usa las implementaciones de Z.ai por defecto (backward compatible).

### Tests individuales

- Test: `ZaiAuth` implementa `PlatformAuth` (hereda correctamente).
- Test: `ZaiChat` implementa `PlatformChat`.
- Test: `ZaiLinks` parsea `/s/` y `/c/` correctamente.
- Test: `ZaiLLM.complete()` envía un prompt y recibe una respuesta (mock del HTTP).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/platform/interfaces.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/platform/zai/zai_auth.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/platform/zai/zai_chat.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/platform/zai/zai_links.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/platform/zai/zai_llm.py
```

---

## F2 — Proxy de subagentes

**Prioridad:** ALTA — es el cambio que libera al agente de la coordinación.
**Dependencias:** F1 (necesita `PlatformLLM`).
**Estimación:** 1 sesión.

### Qué se hace

1. **Crear `mini-services/subagent-proxy/index.ts`** — servicio Bun que:
   - Lee `_pending_tasks.json` periódicamente (cada 2 segundos).
   - Para cada tarea, llama al LLM con el prompt de la tarea (vía `internal-api.z.ai`).
   - Escribe la respuesta en `_responses/{task_id}.txt`.
   - Marca la tarea como procesada (la elimina de `_pending_tasks.json` o la mueve a `_processed_tasks.json`).
   - Funciona en segundo plano (daemon con `bun --hot`).

2. **Crear `mini-services/subagent-proxy/package.json`** — dependencias del proxy.

3. **El proxy usa las mismas credenciales que el proxy de APA**:
   - Lee `/etc/.z-ai-config` para obtener las credenciales reales.
   - Reenvía a `internal-api.z.ai/v1/chat/completions`.
   - Patrón idéntico al `_lib.ts` del proxy de APA.

4. **El proxy soporta paralelismo**:
   - Si hay 10 tareas pendientes, lanza 5 peticiones HTTP en paralelo.
   - Configurable: `MAX_PARALLEL` en el `package.json` o variables de entorno.

### Tests individuales

- Test: el proxy lee una tarea de `_pending_tasks.json` y escribe la respuesta en `_responses/`.
- Test: el proxy procesa múltiples tareas en paralelo.
- Test: el proxy maneja errores del LLM (timeout, 500) sin morir.

### Validación

```bash
cd /home/z/my-project/mini-services/subagent-proxy && bun run dev
# En otra terminal:
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
# Crear una tarea de prueba
from contexto_zai.models import SubagentTask
from contexto_zai.coordinador import EntregadorTareas
from pathlib import Path
ent = EntregadorTareas(workspace_dir='/tmp/test_proxy')
ent.publicar([SubagentTask(task_id='test_1', purpose='test', prompt='Responde: hola')])
# Esperar a que el proxy la procese
import time; time.sleep(10)
# Verificar la respuesta
resp = Path('/tmp/test_proxy/_responses/test_1.txt')
print('Respuesta:', resp.read_text() if resp.exists() else 'no hay')
"
```

---

## F3 — Conectar el proceso al proxy (opt-in)

**Prioridad:** ALTA — integra el proxy con el proceso.
**Dependencias:** F1, F2.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Intervenir `contexto_zai/coordinador/orquestador.py`**:
   - Detectar si el proxy está corriendo (verificar si el servicio responde en su puerto).
   - Si está: el proceso publica tareas y no espera al agente — el proxy las procesa.
   - Si no está: el proceso funciona como hoy (el agente lanza los subagentes).

2. **Intervenir `contexto_zai/pipeline.py`**:
   - `run()` devuelve un mensaje claro: "tareas publicadas, el proxy las está procesando" o "tareas publicadas, lanza los subagentes con el Task tool".
   - `collect_responses()` funciona igual en ambos casos (lee de `_responses/`).

3. **Configurar el puerto del proxy** en `config.py`:
   - `SUBAGENT_PROXY_PORT = 8090` (o el que se decida).
   - `SUBAGENT_PROXY_ENABLED = True/False` (detectable automáticamente).

### Tests individuales

- Test: si el proxy está corriendo, el proceso no le pide al agente que lance subagentes.
- Test: si el proxy no está, el proceso le pide al agente que lance subagentes (backward compatible).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F4 — Tests E2E y medición de latencia

**Prioridad:** ALTA — valida que todo encaja y mide la mejora.
**Dependencias:** F1, F2, F3.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **Test E2E con proxy** en `tests/test_v42_e2e.py`:
   - Iniciar el proxy.
   - Llamar `pipeline.run()`.
   - Verificar que las tareas se procesan automáticamente.
   - Llamar `collect_responses()`.
   - Verificar que los archivos se actualizan.

2. **Medición de latencia**:
   - Medir tiempo de `pipeline.run()` → `collect_responses()` con proxy vs. sin proxy.
   - Medir tiempo por subagente (proxy vs. Task tool).
   - Documentar los resultados.

3. **Verificación final**:
   ```bash
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/run_all_tests.py
   cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
   cd /home/z/my-project && bun run lint
   ```

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias |
|---|---|---|
| F1 — Interfaces + implementaciones Z.ai | Sesión 20 (1.5) | ninguna |
| F2 — Proxy de subagentes | Sesión 20 (1.0) | F1 |
| F3 — Conectar proceso al proxy (opt-in) | Sesión 21 (0.5) | F1, F2 |
| F4 — Tests E2E + latencia | Sesión 21 (0.5) | F1, F2, F3 |

**Total estimado:** 3.5 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El proxy no puede acceder a `internal-api.z.ai` | Baja | Alto | Reutilizar el patrón del proxy de APA que ya funciona. |
| El LLM directo no responde igual que el Task tool | Media | Medio | Los prompts son los mismos; el LLM es el mismo (glm-4-plus). |
| La separación de plataforma rompe el código existente | Baja | Alto | Usar patrón Adapter (envolver, no reemplazar). Tests + E2E. |
| El proxy muere en segundo plano | Media | Medio | Daemon con `bun --hot` (auto-restart). El proceso detecta si el proxy no responde y cae al modo agente. |
| Latencia del proxy mayor a la esperada | Baja | Medio | Medición en F4. Si es peor, investigar y optimizar. |

---

**Fin del plan v5.0.**
