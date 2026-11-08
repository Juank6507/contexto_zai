# contexto_zai/Documentos/plan_refactorizacion_v6.2.md
# Plan v6.2 — Fallback al agente con subagentes cuando el proxy APA falla

**Versión:** 6.2
**Fecha:** 2026-09-27
**Autor:** Agente CZAI (Sesión 24, con consenso del Director)
**Estado:** 🚧 Pendiente de implementación.
**Continúa de:** plan v6.1 (optimización de la cascada: fusión, backoff, cache, modelo dual).
**Spec asociada:** spec_recuperacion_contexto_v6.2.md.

---

## Estructura del plan

El plan se organiza en 5 fases (F1-F5), todas sobre código Python (el Worker Bun
v6.1 no se toca). La premisa del Director es simple: **el proxy APA es el
primario, si falla el agente lanza subagentes como antes**.

1. F1 — `Bloque.tiene_resumen()` + helpers de detección.
2. F2 — `_proxy_apa_disponible()` + `_arrancar_worker_y_esperar()`.
3. F3 — `_construir_pending_task_para_bloque()` + `_enriquecer_bloques_con_fallback()`.
4. F4 — Integración en `pipeline.run()` + constantes en `config.py`.
5. F5 — Tests E2E (3 escenarios: proxy OK, proxy caído, proxy cae a mitad).

**Total de archivos nuevos:** 0.
**Total de archivos intervenidos:** 4 (`pipeline.py`, `models.py`, `config.py`,
  `tests/test_v42_e2e.py`).
**Tests nuevos:** 5 E2E.

---

## F1 — `Bloque.tiene_resumen()` + helpers de detección

**Prioridad:** ALTA — base para que el pipeline detecte qué bloques faltan.
**Dependencias:** ninguna.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.3 sesión.

### Qué se hace

1. **`models.py`** — añadir método `tiene_resumen()` a la clase `Bloque`:
   ```python
   def tiene_resumen(self) -> bool:
       """Devuelve True si el archivo físico del bloque empieza con 'RESUMEN:'."""
       if not self.path or not Path(self.path).exists():
           return False
       try:
           with open(self.path, "r", encoding="utf-8") as f:
               first_line = f.readline().strip()
           return first_line.startswith("RESUMEN:")
       except Exception:
           return False
   ```

2. **`pipeline.py`** — añadir helper `_bloques_sin_resumen(blocks)`:
   ```python
   def _bloques_sin_resumen(blocks: list[Bloque]) -> list[Bloque]:
       """Filtra los bloques que no tienen RESUMEN: al inicio."""
       return [b for b in blocks if not b.tiene_resumen()]
   ```

### Tests individuales

- Test: `Bloque.tiene_resumen()` devuelve True si el archivo empieza con `RESUMEN:`.
- Test: `Bloque.tiene_resumen()` devuelve False si el archivo no empieza con `RESUMEN:`.
- Test: `Bloque.tiene_resumen()` devuelve False si el archivo no existe.
- Test: `_bloques_sin_resumen()` filtra correctamente.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/models.py
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 -c "
from contexto_zai.pipeline import _bloques_sin_resumen
from contexto_zai.models import Bloque
# crear bloques de test...
"
```

---

## F2 — `_proxy_apa_disponible()` + `_arrancar_worker_y_esperar()`

**Prioridad:** ALTA — permite detectar si el proxy funciona y arrancar el worker.
**Dependencias:** F1.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.5 sesión.

### Qué se hace

1. **`pipeline.py`** — añadir `_proxy_apa_disponible()`:
   ```python
   def _proxy_apa_disponible() -> bool:
       """Hace un ping mínimo al proxy APA. Devuelve True si responde 200."""
       import requests
       from contexto_zai.config import PROXY_APA_URL, PROXY_APA_TIMEOUT
       try:
           resp = requests.post(
               PROXY_APA_URL,
               json={
                   "model": "glm-4-flash",
                   "messages": [{"role": "user", "content": "ping"}],
                   "max_tokens": 3,
               },
               timeout=PROXY_APA_TIMEOUT,
           )
           return resp.status_code == 200
       except Exception:
           return False
   ```

2. **`pipeline.py`** — añadir `_arrancar_worker_y_esperar()`:
   ```python
   def _arrancar_worker_y_esperar(workspace_dir: Path, timeout: int = 120) -> bool:
       """Arranca el Worker Bun y espera a que termine.
       Devuelve True si el worker completó (exit code 0), False si falló o timeout.
       """
       import subprocess
       from contexto_zai.config import WORKER_BUN_DIR, WORKER_BUN_TIMEOUT
       try:
           result = subprocess.run(
               ["bun", "run", "cli.ts", "run"],
               cwd=WORKER_BUN_DIR,
               env={**os.environ, "CZAI_WORKSPACE_DIR": str(workspace_dir)},
               timeout=timeout or WORKER_BUN_TIMEOUT,
               capture_output=True,
               text=True,
           )
           if result.returncode == 0:
               log.info("Worker Bun completó exitosamente.")
               return True
           log.warning(f"Worker Bun falló (exit code {result.returncode}).")
           log.warning(f"stderr: {result.stderr[:500]}")
           return False
       except subprocess.TimeoutExpired:
           log.warning(f"Worker Bun timeout tras {timeout}s.")
           return False
       except Exception as e:
           log.warning(f"Error arrancando Worker Bun: {e}")
           return False
   ```

3. **`config.py`** — añadir constantes:
   ```python
   # v6.2: Fallback al agente
   PROXY_APA_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions"
   PROXY_APA_TIMEOUT = 10  # segundos para el ping
   WORKER_BUN_TIMEOUT = 120  # segundos para que el worker procese todos los bloques
   WORKER_BUN_DIR = "/home/z/my-project/contexto_zai/mini-services/worker-cascade"
   ```

### Tests individuales

- Test: `_proxy_apa_disponible()` devuelve True cuando el proxy responde 200 (mock).
- Test: `_proxy_apa_disponible()` devuelve False cuando el proxy responde 429 (mock).
- Test: `_proxy_apa_disponible()` devuelve False cuando el proxy no responde (mock).
- Test: `_arrancar_worker_y_esperar()` devuelve True cuando el worker completa (mock subprocess).
- Test: `_arrancar_worker_y_esperar()` devuelve False cuando el worker timeout (mock subprocess).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F3 — `_construir_pending_task_para_bloque()` + `_enriquecer_bloques_con_fallback()`

**Prioridad:** ALTA — orquestación principal de la Fase 2 con fallback.
**Dependencias:** F1, F2.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.7 sesión.

### Qué se hace

1. **`pipeline.py`** — añadir `_construir_pending_task_para_bloque()`:
   ```python
   def _construir_pending_task_para_bloque(
       bloque: Bloque,
       chat_label: str,
       metadata: RecoveryMetadata,
   ) -> PendingTask:
       """Construye una PendingTask para que un subagente procese el bloque."""
       prompt = f"""Lee el bloque {bloque.filename} en {bloque.path}.

   Genera un resumen abarcador del tema de este bloque. El resumen debe capturar:
   1. Tema central
   2. Decisiones
   3. Temas
   4. Actividad (debugging/diseño/implementación/discusión)

   Escribe el resumen al inicio del archivo con el prefijo 'RESUMEN: '.

   Después, basándote en el resumen, extrae:
   - nombre legible en snake_case (máximo 5 palabras)
   - decisiones con formato 'DECISION: ... | ALCANCE: ...'
   - temas principales en snake_case (máximo 5)

   Escribe los 3 archivos en _responses/:
   - {bloque.block_id}_nombre.txt
   - {bloque.block_id}_decisiones.txt
   - {bloque.block_id}_temas.txt
   """
       return PendingTask(
           task_id=f"enriquecer_{bloque.block_id}",
           prompt=prompt,
           response_file=f"_responses/{bloque.block_id}_extract.txt",
       )
   ```

2. **`pipeline.py`** — añadir `_enriquecer_bloques_con_fallback()`:
   ```python
   def _enriquecer_bloques_con_fallback(
       blocks: list[Bloque],
       workspace_dir: Path,
       chat_label: str,
       metadata: RecoveryMetadata,
   ) -> list[PendingTask]:
       """Fase 2: enriquecer bloques con resumen + extracción, con fallback al agente."""
       pending_tasks = []

       bloques_sin_resumen = _bloques_sin_resumen(blocks)

       if not bloques_sin_resumen:
           log.info("Todos los bloques ya tienen resumen. Nada que hacer.")
           return pending_tasks

       proxy_ok = _proxy_apa_disponible()
       log.info(f"Proxy APA: {'disponible' if proxy_ok else 'no disponible'}")

       if proxy_ok:
           log.info(f"Arrancando Worker Bun para {len(bloques_sin_resumen)} bloques...")
           worker_ok = _arrancar_worker_y_esperar(workspace_dir=workspace_dir)

           if worker_ok:
               bloques_aun_sin_resumen = _bloques_sin_resumen(bloques_sin_resumen)
               if not bloques_aun_sin_resumen:
                   log.info("Worker Bun completó todos los bloques. Fallback no necesario.")
                   return pending_tasks
               log.info(f"Worker Bun falló en {len(bloques_aun_sin_resumen)} bloques. Fallback al agente.")
               bloques_para_fallback = bloques_aun_sin_resumen
           else:
               log.info("Worker Bun no completó. Fallback al agente para todos los bloques.")
               bloques_para_fallback = bloques_sin_resumen
       else:
           log.info("Proxy APA no disponible. Fallback al agente para todos los bloques.")
           bloques_para_fallback = bloques_sin_resumen

       for bloque in bloques_para_fallback:
           task = _construir_pending_task_para_bloque(bloque, chat_label, metadata)
           pending_tasks.append(task)

       return pending_tasks
   ```

### Tests individuales

- Test: `_construir_pending_task_para_bloque()` devuelve una PendingTask con
  prompt que incluye la ruta del bloque y las instrucciones.
- Test: `_enriquecer_bloques_con_fallback()` con proxy OK y worker OK →
  `pending_tasks` vacío.
- Test: `_enriquecer_bloques_con_fallback()` con proxy caído → `pending_tasks`
  con N tareas (una por bloque sin resumen).
- Test: `_enriquecer_bloques_con_fallback()` con proxy OK pero worker falla →
  `pending_tasks` con N tareas.
- Test: `_enriquecer_bloques_con_fallback()` con todos los bloques ya con
  resumen → `pending_tasks` vacío (no hace nada).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F4 — Integración en `pipeline.run()` + constantes en `config.py`

**Prioridad:** ALTA — conecta todo.
**Dependencias:** F1, F2, F3.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.3 sesión.

### Qué se hace

1. **`pipeline.py`** — modificar `run()` para llamar a `_enriquecer_bloques_con_fallback()`
   después de la Fase 1:

   ```python
   def run(chat_id, jwt, trigger, reason, ...) -> OrchestratorResult:
       # Fase 1: local (siempre, sin LLM) — ya existe
       blocks = extraer_clasificar_empaquetar(...)
       generar_archivos_basicos(blocks, ...)

       # Fase 2: enriquecimiento con LLM (con fallback) — NUEVO v6.2
       pending_tasks = _enriquecer_bloques_con_fallback(
           blocks=blocks,
           workspace_dir=workspace_dir,
           chat_label=chat_label,
           metadata=metadata,
       )

       return OrchestratorResult(
           blocks=blocks,
           pending_tasks=pending_tasks,
           ...
       )
   ```

2. **`config.py`** — añadir constantes (ya listadas en F2).

### Tests individuales

- Test: `run()` con proxy OK → `pending_tasks` vacío (el worker procesa todo).
- Test: `run()` con proxy caído → `pending_tasks` con N tareas.
- Test: `run()` no rompe si `_enriquecer_bloques_con_fallback()` falla (catch
  y devuelve `pending_tasks` vacío para no bloquear el pipeline).

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/pipeline.py
```

---

## F5 — Tests E2E (5 escenarios)

**Prioridad:** ALTA — valida que todo encaja.
**Dependencias:** F1, F2, F3, F4.
**Estado:** 🚧 Pendiente.
**Estimación:** 0.7 sesión.

### Qué se hace

Añadir 5 tests E2E en `tests/test_v42_e2e.py`:

#### Test E2E 1 — proxy APA disponible

- Mock del proxy APA que siempre responde 200.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 arranca worker → worker
  procesa todo → `pending_tasks` vacío.
- Verificar: todos los bloques tienen `RESUMEN:`, `_responses/` tiene los 4
  archivos por bloque, `pending_tasks == []`.

#### Test E2E 2 — proxy APA caído

- Mock del proxy APA que siempre responde 429.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 detecta proxy caído →
  construye `pending_tasks` para todos los bloques → devuelve resultado.
- Verificar: `pending_tasks` tiene 14 tareas (una por bloque), los bloques no
  tienen `RESUMEN:` (el worker no corrió).

#### Test E2E 3 — proxy APA cae a mitad

- Mock del proxy APA que responde 200 para los primeros 10 bloques y 429 para
  los últimos 4.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 arranca worker → worker
  procesa 10, falla en 4 → `pending_tasks` tiene 4 tareas.
- Verificar: 10 bloques tienen `RESUMEN:`, 4 no, `pending_tasks` tiene 4 tareas
  (solo para los bloques sin resumen).

#### Test E2E 4 — timeout del worker

- Mock del worker que cuelga (no termina).
- `pipeline.run()` → Fase 2 arranca worker → timeout tras 120s → construye
  `pending_tasks` para todos los bloques.
- Verificar: `pending_tasks` tiene 14 tareas.

#### Test E2E 5 — re-correr con proxy recuperado

- Primera corrida: proxy caído → 14 pending_tasks → agente lanza subagentes →
  bloques quedan con `RESUMEN:`.
- Segunda corrida: proxy recuperado → Fase 2 detecta que todos los bloques ya
  tienen `RESUMEN:` → `pending_tasks` vacío → no hace nada.
- Verificar: no se consumen llamadas LLM del proxy en la segunda corrida.

### Validación

```bash
cd /home/z/my-project && PYTHONPATH=/home/z/my-project python3 contexto_zai/tests/test_v42_e2e.py
```

---

## Orden de ejecución

| Fase | Sesión estimada | Dependencias | Estado |
|---|---|---|---|
| F1 — `Bloque.tiene_resumen()` + helpers | Sesión 24 (0.3) | ninguna | 🚧 Pendiente |
| F2 — `_proxy_apa_disponible()` + `_arrancar_worker_y_esperar()` | Sesión 24 (0.5) | F1 | 🚧 Pendiente |
| F3 — `_construir_pending_task_para_bloque()` + `_enriquecer_bloques_con_fallback()` | Sesión 24 (0.7) | F1, F2 | 🚧 Pendiente |
| F4 — Integración en `pipeline.run()` + `config.py` | Sesión 24 (0.3) | F1, F2, F3 | 🚧 Pendiente |
| F5 — Tests E2E (5 escenarios) | Sesión 24 (0.7) | F1-F4 | 🚧 Pendiente |

**Total estimado:** 2.5 sesiones.

## Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| El subprocess del worker cuelga indefinidamente | Media | Alto | Timeout de 120s en `subprocess.run()`. Si timeout, fallback al agente. |
| El proxy APA responde 200 al ping pero 429 al procesar bloques | Alta | Medio | El worker tiene su propio backoff exponencial. Si falla, el pipeline detecta bloques sin `RESUMEN:` y los manda a `pending_tasks`. |
| El agente lanza subagentes pero estos no generan los archivos esperados | Media | Medio | El prompt de `_construir_pending_task_para_bloque()` es explícito sobre qué archivos escribir. `collect_responses()` verifica que existan. |
| `Bloque.tiene_resumen()` da falso positivo por contenido residual | Baja | Bajo | Verifica que la primera línea empiece con `RESUMEN:` exactamente. |
| El worker processa bloques en orden distinto al esperado | Baja | Bajo | No importa el orden: el pipeline filtra por `tiene_resumen()` al final. |
| Race condition: el worker escribe `RESUMEN:` mientras el pipeline lee | Baja | Medio | El worker escribe atómicamente (escribe a temp file y renombra). |

---

**Fin del plan v6.2.**
