# contexto_zai/Documentos/spec_recuperacion_contexto_v6.2.md
# Spec v6.2 — Fallback al agente con subagentes cuando el proxy APA falla

**Versión:** 6.2
**Fecha:** 2026-09-27
**Autor:** Agente CZAI (Sesión 24, con consenso del Director)
**Estado:** Spec pendiente de implementación.
**Especifica continuación de:** spec v6.1 (optimización de la cascada: fusión, backoff, cache, modelo dual).
**Spec asociada:** esta.
**Plan asociado:** plan_refactorizacion_v6.2.md.

---

## 1. Propósito

La v6.1 introdujo 4 optimizaciones a la cascada de workers (fusión W2-4, backoff
exponencial, cache por hash, modelo dual) que redujeron el consumo de cuota del
LLM de 56 a 28 llamadas para 14 bloques. Sin embargo, al probar el proceso
end-to-end con datos reales (chat EP 02) surgió un problema:

**El proxy APA del sandbox tiene una cuota diaria que se agota tras ~20 llamadas.**

El backoff exponencial de v6.1 está diseñado para 429s transitorios (ventanas de
~3 min), no para cuotas diarias agotadas. Cuando la cuota se agota, el Worker Bun
se queda reintentando hasta que `MAX_RETRIES` se agota, marca los bloques como
`failed`, y el proceso no completa.

La v6.2 resuelve esto con una **decisión simple y elegante** del Director:

> Antes de cada bloque o grupo de bloques el proceso comprueba si el proxy
> responde, se ejecuta la tarea, al terminar se comprueba si llegó a feliz
> término. Si falla alguna de estas premisas se ejecuta exactamente igual que se
> hacía anterior al uso del proxy (se manda la tarea al `pending_tasks` y se
> vuelve a ejecutar por el agente lanzando subagentes). Siempre se reintenta y
> como prioridad el uso del proxy ya que limita el efecto colateral de uso de
> contexto del agente.

### 1.1. Por qué no Solución D (MB externo)

Se consideró usar Model Broker (MB) como capa primaria externa al sandbox, pero
el Director decidió que **no compensa complicar el proceso con cosas externas**.
La solución v6.2 es más simple, no introduce dependencias, y cumple con las
expectativas del proceso: **siempre completa, con la mejor calidad disponible**.

### 1.2. Principio rector

> **El proxy APA es el primario. Si falla, el agente asume el trabajo con
> subagentes como antes. El agente solo gasta ventana cuando el proxy no está
> disponible.**

En las sesiones donde el proxy funciona, el agente no toca los bloques. En las
sesiones donde el proxy está saturado, el agente lanza subagentes (uno por
bloque pendiente) y estos generan los resúmenes y extracciones.

## 2. Los 4 problemas que la v6.2 ataca

| # | Problema | Causa raíz |
|---|---|---|
| 1 | El Worker Bun v6.1 no completa cuando el proxy APA agota su cuota diaria | El backoff exponencial maneja 429s transitorios, no cuotas agotadas |
| 2 | El proceso no tiene fallback: si el worker falla, los bloques quedan sin resumen | `pipeline.run()` no orquesta el fallback al flujo de subagentes |
| 3 | El agente principal gasta ventana de contexto en tareas que el worker debería hacer | Cuando el proxy funciona, el agente no debería intervenir; cuando falla, sí |
| 4 | No hay forma de detectar "el worker completó felizmente" desde Python | El worker escribe `_processed_blocks.json` pero el pipeline no lo consulta |

## 3. La solución: orquestación proxy-APA → fallback-agente

### 3.1. Flujo del pipeline.run() con fallback

```
pipeline.run(chat_id, jwt, ...)
    │
    ├─ Fase 1: Local (siempre, sin LLM)
    │   ├─ Extraer mensajes del chat (ChatClient)
    │   ├─ Construir exchanges (ExchangeBuilder)
    │   ├─ Clasificar por temas (MessageClassifier)
    │   ├─ Empaquetar en bloques (BlockPacker)
    │   ├─ Generar metadata (MetadataManager)
    │   ├─ Generar 03_objetivo_proyecto.md (EstadoGenerator)
    │   ├─ Generar 00_estado_actual.md (EstadoGenerator)
    │   ├─ Generar 01_indice_recuperacion.md (IndiceGenerator)
    │   └─ Generar 02_decisiones_clave.md (DecisionesGenerator)
    │
    └─ Fase 2: Enriquecimiento con LLM (con fallback)
        │
        ├─ Identificar bloques sin RESUMEN: (que W1 no procesó)
        │
        ├─ Para cada bloque (o grupo de bloques):
        │   │
        │   ├─ CHECK: ¿proxy APA disponible?
        │   │   (POST al proxy con un ping mínimo)
        │   │
        │   ├─ Si SÍ:
        │   │   ├─ Arrancar Worker Bun para ese bloque (o grupo)
        │   │   ├─ Esperar a que termine (con timeout)
        │   │   ├─ CHECK al terminar: ¿llegó a feliz término?
        │   │   │   ├─ SÍ (bloque tiene RESUMEN: + _responses/ tiene nombre/decisiones/temas)
        │   │   │   │   → continuar con el siguiente bloque
        │   │   │   └─ NO (timeout, worker murió, o 429 persistente)
        │   │   │       → añadir bloque a pending_tasks (fallback)
        │   │   │
        │   └─ Si NO (proxy caído):
        │       └─ añadir bloque a pending_tasks (fallback)
        │
        └─ Si pending_tasks no está vacío:
            └─ Devolver OrchestratorResult(pending_tasks=pending_tasks)
               → El agente principal lanza subagentes con Task tool
               → Cada subagente lee su bloque, genera resumen + extracción
               → El agente llama a collect_responses() para integrarlos
```

### 3.2. Diferencia con v6.0/v6.1

| Aspecto | v6.0/v6.1 | v6.2 |
|---|---|---|
| Cuando el proxy funciona | Worker Bun procesa todo | Worker Bun procesa todo (igual) |
| Cuando el proxy falla | Bloques quedan `failed`, proceso no completa | El agente lanza subagentes para los bloques fallidos |
| Cuándo se decide el fallback | Nunca (no hay fallback) | Por bloque: si el worker falla ESE bloque, fallback para ESE bloque |
| Ventana del agente | 0 tokens siempre (cuando proxy OK) | 0 tokens si proxy OK; tokens proporcionales a bloques fallidos si proxy caído |
| Cuota del proxy | Se consume sin límite | Se prefiere siempre, pero si falla se cae al fallback |

### 3.3. Granularidad del fallback: por bloque, no global

**Decisión**: si el worker procesa 10 de 14 bloques y falla en 4, los
`pending_tasks` solo contienen las 4 tareas faltantes, no las 14. Esto minimiza
el gasto de ventana del agente.

**Implementación**: el pipeline identifica qué bloques tienen `RESUMEN:` al inicio
del archivo físico (señal de que W1 completó) y cuáles no. Los que no, van a
`pending_tasks`.

### 3.4. Prioridad del proxy: siempre se reintenta

**Decisión del Director**: "Siempre se reintenta y como prioridad el uso del
proxy ya que limita el efecto colateral de uso de contexto del agente."

**Implementación**: el pipeline siempre intenta el proxy primero. Si el proxy
falla para un bloque, ese bloque va a `pending_tasks`. Pero en la próxima corrida
del pipeline (o si el Director pide re-procesar), el pipeline vuelve a intentar
el proxy primero para los bloques que aún no tienen `RESUMEN:`. Solo si el proxy
sigue fallando, el bloque va de nuevo a `pending_tasks`.

## 4. Dónde vive la lógica de orquestación

La lógica de "proxy disponible → worker, si no → fallback" vive en
**`pipeline.run()`** (Python), no en el Worker Bun ni en el agente. Esto cumple
con el DTI: **el proceso es el bibliotecario que sirve al agente**.

### 4.1. Componentes nuevos en Python

#### `pipeline.py` — `_enriquecer_bloques_con_fallback()`

Nuevo método privado que orquesta la Fase 2:

```python
def _enriquecer_bloques_con_fallback(
    blocks: list[Bloque],
    workspace_dir: Path,
    chat_label: str,
    metadata: RecoveryMetadata,
) -> list[PendingTask]:
    """Fase 2: enriquecer bloques con resumen + extracción.

    - Si el proxy APA está disponible: arranca el Worker Bun por bloque (o grupo).
    - Si el proxy falla o el worker no completa: añade a pending_tasks para
      que el agente lance subagentes (fallback).

    Devuelve la lista de pending_tasks (vacía si todo OK, con tareas si falló).
    """
    pending_tasks = []

    # Bloques sin RESUMEN: al inicio (W1 no procesó)
    bloques_sin_resumen = [b for b in blocks if not b.tiene_resumen()]

    if not bloques_sin_resumen:
        log.info("Todos los bloques ya tienen resumen. Nada que hacer.")
        return pending_tasks

    # CHECK proxy APA
    proxy_ok = _proxy_apa_disponible()
    log.info(f"Proxy APA: {'disponible' if proxy_ok else 'no disponible'}")

    if proxy_ok:
        # Arrancar Worker Bun para los bloques sin resumen
        log.info(f"Arrancando Worker Bun para {len(bloques_sin_resumen)} bloques...")
        worker_ok = _arrancar_worker_y_esperar(
            workspace_dir=workspace_dir,
            timeout=120,  # 120s para 14 bloques
        )

        if worker_ok:
            # Re-verificar qué bloques quedaron sin resumen
            bloques_aun_sin_resumen = [
                b for b in bloques_sin_resumen if not b.tiene_resumen()
            ]
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

    # Construir pending_tasks para los bloques que el worker no procesó
    for bloque in bloques_para_fallback:
        task = _construir_pending_task_para_bloque(bloque, chat_label, metadata)
        pending_tasks.append(task)

    return pending_tasks
```

#### `pipeline.py` — `_proxy_apa_disponible()`

```python
def _proxy_apa_disponible() -> bool:
    """Hace un ping mínimo al proxy APA. Devuelve True si responde 200."""
    import requests
    try:
        resp = requests.post(
            "http://localhost:3000/api/zai-proxy/v1/chat/completions",
            json={
                "model": "glm-4-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 3,
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False
```

#### `pipeline.py` — `_arrancar_worker_y_esperar()`

```python
def _arrancar_worker_y_esperar(
    workspace_dir: Path,
    timeout: int = 120,
) -> bool:
    """Arranca el Worker Bun y espera a que termine.

    Devuelve True si el worker completó (exit code 0), False si falló o timeout.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["bun", "run", "cli.ts", "run"],
            cwd="/home/z/my-project/contexto_zai/mini-services/worker-cascade",
            env={**os.environ, "CZAI_WORKSPACE_DIR": str(workspace_dir)},
            timeout=timeout,
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

#### `models.py` — `Bloque.tiene_resumen()`

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

#### `pipeline.py` — `_construir_pending_task_para_bloque()`

```python
def _construir_pending_task_para_bloque(
    bloque: Bloque,
    chat_label: str,
    metadata: RecoveryMetadata,
) -> PendingTask:
    """Construye una PendingTask para que un subagente procese el bloque.

    La tarea pide al subagente que:
    1. Lea el bloque completo.
    2. Genere un resumen (tema central, decisiones, temas, actividad).
    3. Escriba el resumen al inicio del bloque físico (RESUMEN: ...).
    4. Extraiga nombre legible, decisiones, temas.
    5. Escriba los 3 archivos en _responses/.
    """
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

### 4.2. Integración en `pipeline.run()`

El método `run()` existente se modifica para llamar a `_enriquecer_bloques_con_fallback()`
después de la Fase 1 (generación de archivos básicos):

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

    # Devolver resultado
    return OrchestratorResult(
        blocks=blocks,
        pending_tasks=pending_tasks,
        ...
    )
```

### 4.3. Worker Bun v6.1: sin cambios

El Worker Bun (`mini-services/worker-cascade/index.ts`) **no se modifica**. Ya
tiene el backoff exponencial, el cache, el modelo dual. El pipeline lo arranca
vía `subprocess.run()` y espera a que termine.

El worker ya no aborta si el proxy está en 429 al arrancar (modificación de la
sesión anterior). Procesa lo que puede y marca los que no pudo como `failed`.

## 5. Lo que se conserva de versiones anteriores

Todo lo de v6.1 y anteriores:

- **Worker Bun v6.1** con las 4 optimizaciones (fusión, backoff, cache, modelo dual).
- **Cascada W1 → W2-fusionado** del worker.
- **`_pending_blocks.json`** y **`_processed_blocks.json`** como archivos de estado.
- **`_responses/`** como directorio de salida.
- **Cache por hash SHA256** en `_responses/cache/`.
- **Backoff exponencial** `[2, 4, 8, 16, 32, 64]s`.
- **Modelo dual** `glm-4-plus` (W1) + `glm-4-flash` (W2).
- Todo lo heredado de v5.0 (proxy de subagentes), v4.x (4 archivos de recuperación,
  lógica de 4 casos, soporte multi-chat, etc.).

## 6. Lo que se añade en v6.2

- **`pipeline._enriquecer_bloques_con_fallback()`** — orquesta la Fase 2 con
  fallback al agente.
- **`pipeline._proxy_apa_disponible()`** — ping al proxy APA.
- **`pipeline._arrancar_worker_y_esperar()`** — arranca el Worker Bun vía
  subprocess con timeout.
- **`pipeline._construir_pending_task_para_bloque()`** — construye PendingTask
  para que un subagente procese un bloque.
- **`Bloque.tiene_resumen()`** — método que verifica si el bloque tiene `RESUMEN:`
  al inicio.
- **Integración en `pipeline.run()`** — la Fase 2 ahora orquesta proxy → fallback.

## 7. Lo que migra / se queda / se elimina

### 7.1. Migra

| Componente | Antes (v6.1) | Después (v6.2) |
|---|---|---|
| Fase 2 del pipeline | No existía (el agente decidía cuándo lanzar el worker) | El pipeline orquesta: arranca worker, espera, fallback si falla |
| Detección de bloques sin resumen | El worker las filtraba internamente | El pipeline las identifica antes de arrancar el worker |
| `pending_tasks` | Solo se construía para subagentes de consulta | Se construye también para bloques que el worker no procesó |

### 7.2. Se queda (sin cambios)

- Worker Bun v6.1 completo (`mini-services/worker-cascade/`).
- `OrchestratorResult` con `pending_tasks`.
- `collect_responses()` para integrar respuestas de subagentes.
- 4 archivos de recuperación (00, 01, 02, 03).
- Todo el flujo de la Fase 1 (extracción, clasificación, empaquetado).

### 7.3. Se elimina

- Nada. La v6.2 es aditiva: añade fallback sin quitar nada.

## 8. Reglas de implementación

- **Cambios quirúrgicos**: solo se añade `_enriquecer_bloques_con_fallback()` y
  helpers. No se toca la Fase 1 ni el Worker Bun.
- **Scripts atómicos**: `pipeline.py` es un script de dependencia (importa
  atómicos), se valida con tests E2E en `tests/test_v42_e2e.py`.
- **OOP**: las nuevas funciones son métodos privados de `Pipeline` o helpers
  del módulo.
- **No hardcoding**: timeout, URL del proxy, y comando del worker van en
  `config.py`.
- **Tests E2E**: 3 escenarios nuevos (proxy OK, proxy caído, proxy cae a mitad).
- **Comentario en primera línea**: todo archivo intervenido lleva su ruta de
  destino y resumen (DTI regla 6).

## 9. Compatibilidad con v6.1

- Si el proxy APA funciona: el pipeline arranca el worker, este procesa todo,
  `pending_tasks` queda vacío, el agente no interviene. **Comportamiento
  idéntico a v6.1**.
- Si el proxy APA no funciona: el pipeline construye `pending_tasks` para los
  bloques sin resumen, el agente lanza subagentes. **Comportamiento idéntico
  a v5.0** (antes del Worker Bun).
- El Worker Bun v6.1 no se modifica: sigue siendo arrancable standalone con
  `bun run cli.ts run`.

## 10. Dependencias nuevas

Ninguna. El pipeline usa `subprocess` (built-in Python) para arrancar el worker.
No se añaden paquetes pip.

## 11. Validación

### 11.1. Test E2E 1 — proxy APA disponible

- Mock del proxy APA que siempre responde 200.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 arranca worker → worker
  procesa todo → `pending_tasks` vacío.
- Verificar: todos los bloques tienen `RESUMEN:`, `_responses/` tiene los 4
  archivos por bloque, `pending_tasks == []`.

### 11.2. Test E2E 2 — proxy APA caído

- Mock del proxy APA que siempre responde 429.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 detecta proxy caído →
  construye `pending_tasks` para todos los bloques → devuelve resultado.
- Verificar: `pending_tasks` tiene 14 tareas (una por bloque), los bloques no
  tienen `RESUMEN:` (el worker no corrió).

### 11.3. Test E2E 3 — proxy APA cae a mitad

- Mock del proxy APA que responde 200 para los primeros 10 bloques y 429 para
  los últimos 4.
- `pipeline.run()` → Fase 1 genera bloques → Fase 2 arranca worker → worker
  procesa 10, falla en 4 → `pending_tasks` tiene 4 tareas.
- Verificar: 10 bloques tienen `RESUMEN:`, 4 no, `pending_tasks` tiene 4 tareas
  (solo para los bloques sin resumen).

### 11.4. Test E2E 4 — timeout del worker

- Mock del worker que cuelga (no termina).
- `pipeline.run()` → Fase 2 arranca worker → timeout tras 120s → construye
  `pending_tasks` para todos los bloques.
- Verificar: `pending_tasks` tiene 14 tareas.

### 11.5. Test E2E 5 — re-correr con proxy recuperado

- Primera corrida: proxy caído → 14 pending_tasks → agente lanza subagentes →
  bloques quedan con `RESUMEN:`.
- Segunda corrida: proxy recuperado → Fase 2 detecta que todos los bloques ya
  tienen `RESUMEN:` → `pending_tasks` vacío → no hace nada.
- Verificar: no se consumen llamadas LLM del proxy en la segunda corrida.

## 12. Configuración nueva en `config.py`

```python
# v6.2: Fallback al agente
PROXY_APA_URL = "http://localhost:3000/api/zai-proxy/v1/chat/completions"
PROXY_APA_TIMEOUT = 10  # segundos para el ping
WORKER_BUN_TIMEOUT = 120  # segundos para que el worker procese todos los bloques
WORKER_BUN_DIR = "/home/z/my-project/contexto_zai/mini-services/worker-cascade"
```

---

**Fin de la spec v6.2.**
